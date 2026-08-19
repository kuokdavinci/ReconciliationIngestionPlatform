"""Report rendering and persistence for quality profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.eda.quality_profile import QualityProfileSpec, build_quality_profile


def render_markdown(profile: dict[str, Any]) -> str:
    """Render a quality profile as a reviewable Markdown report."""

    file_info = profile["file"]
    quality = profile["quality"]
    observations = profile["observations"]
    lines = [
        f"# {profile['dataset']['name']} — Ingestion quality profile",
        "",
        f"- Rows: {file_info['row_count']:,} (valid shape: {file_info['valid_row_count']:,})",
        f"- Columns: {profile['schema']['column_count']}",
        f"- SHA-256: `{file_info['sha256']}`",
        f"- Quality score: {profile['quality_score']}",
        f"- Decision: **{profile['decision']}**",
        "",
        "## Quality Summary",
        "",
        f"- Rejected rows: {quality['rejected_rows']:,}",
        f"- Duplicate rows: {quality['duplicate_rows']:,}",
        f"- Conflicting primary-key groups: {quality['conflicting_primary_key_groups']:,}",
        f"- Missing cells: {quality['null_cell_count']:,}",
        "",
        "## Timestamp",
        "",
        f"- Range: {observations['timestamp_range']['min']} → {observations['timestamp_range']['max']}",
        f"- Rows with second precision: {observations['timestamp_precision']['second_rows']:,}",
        f"- Rows with timezone: {observations['timestamp_precision']['timezone_rows']:,}",
        "",
        "## Amount observations",
        "",
    ]
    for key in (
        "min",
        "q1",
        "median",
        "mean",
        "q3",
        "p95",
        "p99",
        "max",
        "iqr",
        "iqr_upper_bound",
        "outlier_count",
        "outlier_rate",
    ):
        lines.append(f"- {key}: {observations['amount'][key]}")
    lines.extend(
        [
            "",
            "## Rule Results",
            "",
            "| Rule | Severity | Result | Actual | Expected | Action |",
            "|---|---|---|---|---|---|",
        ]
    )
    for result in profile["rule_results"]:
        lines.append(
            f"| `{result['rule_code']}` | {result['severity']} | {result['result']} | "
            f"`{json.dumps(result['actual'], ensure_ascii=False, sort_keys=True)}` | "
            f"`{json.dumps(result['expected'], ensure_ascii=False, sort_keys=True)}` | "
            f"{result['action']} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in profile["limitations"])
    return "\n".join(lines) + "\n"


def write_profile(
    input_path: Path,
    output_dir: Path,
    spec: QualityProfileSpec,
    *,
    distinct_limit: int = 100_000,
    prefix_rows: int | None = None,
) -> tuple[Path, Path]:
    """Build and write JSON/Markdown quality profile artifacts."""

    profile = build_quality_profile(
        input_path,
        spec,
        distinct_limit=distinct_limit,
        prefix_rows=prefix_rows,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "quality_profile.json"
    markdown_path = output_dir / "quality_profile.md"
    json_path.write_text(
        json.dumps(
            profile,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(profile), encoding="utf-8")
    return json_path, markdown_path
