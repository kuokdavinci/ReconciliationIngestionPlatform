"""Service for resolving context for AI mapping generation."""

from typing import Optional
from src.core.enums import FileType
from src.models.mapping_config import MappingConfig, MappingConfigRepository

async def resolve_ai_generation_context(db, packet, existing_draft: Optional[MappingConfig]) -> dict:
    """Resolve headers, sample rows, and parsing structures for the AI mapping config generator."""
    headers = []
    sample_rows = []
    header_row_index = None
    first_data_row_index = None

    packet_signature = getattr(packet, "structure_signature", None) or {}
    if packet_signature:
        headers = list(packet_signature.get("headers") or [])
        sample_rows = list(packet_signature.get("sampleRows") or [])
        header_row_index = packet_signature.get("headerRowIndex")
        first_data_row_index = packet_signature.get("firstDataRowIndex")

    if existing_draft is not None and not headers:
        draft_signature = getattr(existing_draft, "structure_signature", None) or {}
        headers = list(draft_signature.get("headers") or [])
        sample_rows = sample_rows or list(draft_signature.get("sampleRows") or [])
        header_row_index = header_row_index if header_row_index is not None else draft_signature.get("headerRowIndex")
        first_data_row_index = first_data_row_index if first_data_row_index is not None else draft_signature.get("firstDataRowIndex")

    if not headers:
        mapping_repo = MappingConfigRepository(db)
        file_type_value = getattr(packet, "file_type_detected", None) or FileType.SETTLEMENT.value
        try:
            file_type = FileType(file_type_value)
        except ValueError:
            file_type = FileType.SETTLEMENT
        approved = await mapping_repo.find_by_partner_and_type(packet.partner, "UPC", file_type)
        if approved is not None:
            approved_signature = getattr(approved, "structure_signature", None) or {}
            headers = list(approved_signature.get("headers") or [])
            sample_rows = sample_rows or list(approved_signature.get("sampleRows") or [])
            header_row_index = header_row_index if header_row_index is not None else approved_signature.get("headerRowIndex")
            first_data_row_index = first_data_row_index if first_data_row_index is not None else approved_signature.get("firstDataRowIndex")

    if not sample_rows:
        packet_preview = getattr(packet, "sample_preview", None) or []
        sample_rows = [
            list(item.get("values") or [])
            for item in packet_preview
            if isinstance(item, dict) and isinstance(item.get("values"), list)
        ]

    return {
        "headers": headers,
        "sample_rows": sample_rows,
        "header_row_index": header_row_index,
        "first_data_row_index": first_data_row_index,
    }
