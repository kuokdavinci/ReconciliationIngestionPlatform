"""Read complete raw records for a stream-scoped Review Packet."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

from src.domain.review.models import ReviewPacket
from src.infrastructure.ingestion.raw_page_repository import RawIngestionPageRepository
from src.readers import create_reader


def _iter_json_records(path: Path) -> Iterator[Any]:
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    records = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("JSON root must be an array or an object with an items array")
    yield from records


def _iter_page_records(path: Path, start_row: int) -> Iterator[Any]:
    if path.suffix.lower() == ".json":
        yield from _iter_json_records(path)
        return

    reader_config = SimpleNamespace(
        start_row=start_row,
        sheet_name=None,
    )
    with create_reader(path, reader_config) as reader:
        yield from reader.iter_rows()


def _page_sort_key(page: Any) -> tuple[int, str]:
    page_number = getattr(page, "page", None)
    created_at = getattr(page, "created_at", None) or ""
    return (page_number if page_number is not None else 2**31, str(created_at))


def _candidate_source_paths(path: str) -> list[Path]:
    """Resolve source paths written by either the API or Airflow container."""

    candidate = Path(path)
    candidates = [candidate]
    if candidate.is_absolute():
        text = str(candidate)
        for source_root, target_root in (
            ("/opt/airflow/app", "/app"),
            ("/app", "/opt/airflow/app"),
        ):
            if text == source_root or text.startswith(f"{source_root}/"):
                candidates.append(Path(target_root + text[len(source_root):]))
    else:
        candidates.extend(
            [
                Path.cwd() / candidate,
                Path("/app") / candidate,
                Path("/opt/airflow/app") / candidate,
            ]
        )
    return list(dict.fromkeys(candidates))


def resolve_review_source_file(packet: ReviewPacket) -> Path:
    source_file_path = str(getattr(packet, "source_file_path", "") or "")
    if not source_file_path:
        raise ValueError("Review packet has no rawStageKey or sourceFilePath")
    for candidate in _candidate_source_paths(source_file_path):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Source file is no longer available: {source_file_path}")


def _read_file_page(
    packet: ReviewPacket,
    source_path: Path,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    structure_signature = packet.structure_signature or {}
    start_row = int(
        structure_signature.get("firstDataRowIndex")
        or (packet.parse_strategy or {}).get("startRow")
        or 1
    )
    rows: list[dict[str, Any]] = []
    total_records = 0
    for row_index, values in enumerate(
        _iter_page_records(source_path, start_row),
        start=1,
    ):
        if offset <= total_records < offset + limit:
            rows.append(
                {
                    "streamRowIndex": row_index,
                    "rowIndex": row_index,
                    "page": None,
                    "sourceUnitKey": source_path.name,
                    "values": values,
                }
            )
        total_records += 1
    return {
        "packetId": str(packet.id),
        "rawStageKey": None,
        "totalRecords": total_records,
        "pageCount": 1,
        "offset": offset,
        "limit": limit,
        "hasMore": offset + limit < total_records,
        "rows": rows,
    }


async def read_review_stream_page(
    *,
    db: Any,
    packet: ReviewPacket,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    """Read one bounded page from every retained raw page in a stream."""

    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit < 1:
        raise ValueError("limit must be positive")

    if not packet.raw_stage_key:
        return _read_file_page(packet, resolve_review_source_file(packet), offset, limit)

    raw_repo = RawIngestionPageRepository(db)
    pages = sorted(await raw_repo.find_for_replay(packet.raw_stage_key), key=_page_sort_key)
    if not pages:
        raise ValueError(
            "No staged raw pages found for rawStageKey; file-level packets must omit rawStageKey."
        )
    rows: list[dict[str, Any]] = []
    page_counts = [getattr(page, "item_count", None) for page in pages]
    known_total = (
        sum(max(int(count), 0) for count in page_counts)
        if page_counts and all(count is not None for count in page_counts)
        else None
    )
    total_records = known_total or 0

    async for record in iter_review_stream_records(
        db=db,
        packet=packet,
        pages=pages,
        raw_repo=raw_repo,
    ):
        stream_index = int(record["streamRowIndex"] or total_records + 1) - 1
        if known_total is None:
            total_records += 1
        if offset <= stream_index < offset + limit:
            rows.append(record)
        if known_total is not None and stream_index >= offset + limit - 1:
            break

    return {
        "packetId": str(packet.id),
        "rawStageKey": packet.raw_stage_key,
        "totalRecords": total_records,
        "pageCount": len(pages),
        "offset": offset,
        "limit": limit,
        "hasMore": offset + limit < total_records,
        "rows": rows,
    }


async def iter_review_stream_records(
    *,
    db: Any,
    packet: ReviewPacket,
    pages: list[Any] | None = None,
    raw_repo: RawIngestionPageRepository | None = None,
):
    """Yield every raw record in deterministic stream order."""

    if not packet.raw_stage_key:
        raise ValueError("Review packet has no rawStageKey stream scope")

    raw_repo = raw_repo or RawIngestionPageRepository(db)
    pages = sorted(
        pages if pages is not None else await raw_repo.find_for_replay(packet.raw_stage_key),
        key=_page_sort_key,
    )
    structure_signature = packet.structure_signature or {}
    start_row = int(
        structure_signature.get("firstDataRowIndex")
        or (packet.parse_strategy or {}).get("startRow")
        or 1
    )

    with tempfile.TemporaryDirectory(prefix="review-raw-") as temp_dir:
        stream_row_index = 1
        for page in pages:
            source_path = str(getattr(page, "local_path", "") or "")
            suffix = Path(source_path or packet.file_name).suffix or ".json"
            destination = str(
                Path(temp_dir)
                / f"{getattr(page, 'source_unit_key', 'page')}{suffix}"
            )
            materialized_path = await raw_repo.materialize(page, destination)
            for row_index, values in enumerate(
                _iter_page_records(Path(materialized_path), start_row),
                start=1,
            ):
                yield {
                    "streamRowIndex": stream_row_index,
                    "rowIndex": row_index,
                    "page": getattr(page, "page", None),
                    "sourceUnitKey": getattr(page, "source_unit_key", ""),
                    "values": values,
                }
                stream_row_index += 1
