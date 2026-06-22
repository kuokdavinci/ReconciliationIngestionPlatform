"""AI-powered MappingConfig generator.

Uses LLM to analyze sample data from a reconciliation file and produce
a MappingConfig (field mappings, start row, mappings) automatically.
Falls back gracefully if LLM is unavailable.
"""

import json
import logging
import re
from typing import Any, Optional

from src.analysis.config import AnalysisConfig
from src.analysis.provider import create_provider
from src.core.types import FieldMapping, FieldMappingType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a reconciliation file format analyzer. Given sample data from a financial 
reconciliation file, generate a MappingConfig that defines how to parse its columns.

FIELD MAPPING RULES:
- STRING: text/identifier column
- DECIMAL: monetary amount (integer or decimal number — use type DECIMAL)
- DATE: date/time column (format: YYYY-MM-DD or DD/MM/YYYY or with time)
- DATE: date/time column (common forms include YYYY-MM-DD, YYYY/MM/DD, DD/MM/YYYY,
  and variants with time)
- CONSTANT: always the same literal value (e.g., currency = "VND")
- MAPPING: status values needing translation (e.g., "SUCCESS" -> "SUCCESS", "FAILED" -> "FAILED")

CANONICAL FIELDS (must map all that are present):
- id (STRING, required): unique transaction identifier
- trace (STRING): partner transaction ID used as reconciliation key
- amount (DECIMAL): transaction amount
- currency (CONSTANT): always "VND" for Vietnamese partners
- status (MAPPING): transaction status with value mapping
- transDate (DATE): transaction date
- extra.service (CONSTANT, optional): set to "PAYMENT" if clearly present
- extra.portal (CONSTANT, optional): portal/platform name if clearly present
- extra.provider (CONSTANT, optional): partner/provider name if clearly present

COLUMN REFERENCE: column numbers are 1-based (column 1 = first column).

MAPPING RULE: for status fields, provide a mapping dictionary that maps 
each observed status value to SUCCESS, FAILED, PENDING, or REVERSED.

If a field cannot be confidently inferred from the sample, omit it rather than inventing a mapping.
Prefer a minimal valid MappingConfig over a speculative one.

Return ONLY valid JSON (no markdown) with this structure:
{
  "startRow": <int: first data row (1-based, 1 = first row)>,
  "sheetName": "<str: sheet name if Excel, else null>",
  "fieldMappings": [
    {"path": "...", "column": <int>, "type": "STRING|DECIMAL|DATE|CONSTANT|MAPPING", 
     "required": <bool>, "constant": "<str if CONSTANT>", "mapping": {<dict if MAPPING>}}
  ],
  "confidence": <float 0.0-1.0>,
  "reasoning": "<str: explain your analysis>"
}
"""


def _format_sample_table(rows: list[list[str]]) -> str:
    """Format sample rows as a pipe-delimited table for LLM consumption."""
    lines = []
    for i, row in enumerate(rows[:12]):
        line = " | ".join(str(c) if c is not None else "" for c in row)
        lines.append(f"Row {i + 1}: {line}")
    return "\n".join(lines)


def _collect_candidate_columns(headers: list[str], sample_rows: list[list[str]]) -> list[dict[str, Any]]:
    max_cols = max([len(headers), *(len(row) for row in sample_rows)], default=len(headers))
    candidates: list[dict[str, Any]] = []
    for idx in range(max_cols):
        header = headers[idx] if idx < len(headers) else None
        header_text = str(header).strip() if header is not None else ""
        values = []
        non_empty = 0
        for row in sample_rows[:10]:
            value = row[idx] if idx < len(row) else None
            text = str(value).strip() if value is not None else ""
            values.append(text)
            if text:
                non_empty += 1
        if not header_text and non_empty == 0:
            continue
        meaningful_header = bool(re.search(r"[A-Za-zÀ-ỹ0-9]", header_text))
        candidates.append({
            "index": idx + 1,
            "header": header_text or f"Column {idx + 1}",
            "non_empty_count": non_empty,
            "sample_values": [value for value in values if value][:3],
            "priority": (2 if meaningful_header else 0) + min(non_empty, 3),
        })
    candidates.sort(key=lambda item: (-item["priority"], -item["non_empty_count"], item["index"]))
    return candidates


def _parse_ai_response(text: str) -> Optional[dict[str, Any]]:
    """Parse LLM response, handling JSON code blocks."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return json.loads(cleaned)


def _build_field_mappings(raw: list[dict]) -> list[FieldMapping]:
    """Convert raw field mapping dicts to FieldMapping objects."""
    result = []
    for fm in raw:
        try:
            ftype = FieldMappingType(fm["type"])
            kwargs: dict[str, Any] = {
                "path": fm["path"],
                "type": ftype,
                "required": fm.get("required", False),
            }
            if ftype == FieldMappingType.CONSTANT:
                constant = fm.get("constant")
                if not constant:
                    continue
                kwargs["constant"] = constant
            else:
                column = fm.get("column")
                if column is None and ftype != FieldMappingType.MAPPING:
                    continue
                kwargs["column"] = column
                if ftype == FieldMappingType.MAPPING:
                    mapping = fm.get("mapping", {})
                    if not mapping:
                        continue
                    kwargs["mapping"] = mapping
            result.append(FieldMapping(**kwargs))
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping invalid field mapping: {fm} — {e}")
    return result


def _looks_like_decimal(value: str) -> bool:
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return False
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", cleaned))


def _looks_like_date(value: str) -> bool:
    cleaned = str(value).strip()
    if not cleaned:
        return False
    patterns = (
        r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$",
        r"\d{4}/\d{2}/\d{2}( \d{2}:\d{2}:\d{2})?$",
        r"\d{2}/\d{2}/\d{4}( \d{2}:\d{2}:\d{2})?$",
    )
    return any(re.fullmatch(p, cleaned) for p in patterns)


def _score_column(path: str, column_index: int, sample_rows: list[list[str]]) -> int:
    score = 0
    for row in sample_rows:
        value = row[column_index] if column_index < len(row) else ""
        value = str(value).strip()
        if not value:
            continue
        score += 1
        if path in {"id", "trace"} and re.search(r"txn|trans|trace|id", value, re.IGNORECASE):
            score += 4
        if path == "amount" and _looks_like_decimal(value):
            score += 4
        if path == "transDate" and _looks_like_date(value):
            score += 4
        if path == "status" and any(token in value.lower() for token in ("success", "thành công", "failed", "pending", "reversed", "thất bại")):
            score += 4
    return score


def _refine_generated_mapping(
    parsed: dict[str, Any],
    headers: list[str],
    sample_rows: list[list[str]],
    first_data_row_index: Optional[int],
) -> dict[str, Any]:
    parsed["startRow"] = first_data_row_index or parsed.get("startRow") or 2
    field_mappings = parsed.get("fieldMappings") or []
    max_cols = max((len(r) for r in sample_rows), default=len(headers))

    header_candidates = {
        "id": ("id", "transid", "transaction", "mstransid"),
        "trace": ("trace", "partner", "invoice", "mahdon", "mahdon", "mshdon", "mstransid"),
        "amount": ("amount", "total", "mstotalamount"),
        "transDate": ("date", "time", "ngay", "hoanthanh"),
        "status": ("status", "trangthai"),
    }

    for fm in field_mappings:
        if getattr(fm, "type", None) == FieldMappingType.CONSTANT:
            continue
        path = getattr(fm, "path", "")
        if path not in header_candidates:
            continue

        best_col = None
        best_score = -1
        for idx in range(max_cols):
            header = str(headers[idx] if idx < len(headers) else "").lower().replace(" ", "")
            score = _score_column(path, idx, sample_rows)
            if any(token in header for token in header_candidates[path]):
                score += 10
            if score > best_score:
                best_score = score
                best_col = idx + 1

        if best_col is not None and best_score > 0:
            fm.column = best_col

    return parsed


async def generate_config_from_samples(
    partner: str,
    headers: list[str],
    sample_rows: list[list[str]],
    *,
    known_constants: Optional[dict[str, str]] = None,
    header_row_index: Optional[int] = None,
    first_data_row_index: Optional[int] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Generate a MappingConfig from sample data using LLM.

    Args:
        partner: Partner name (e.g., "VNPAY").
        headers: Column headers (first row of file).
        sample_rows: Sample data rows.
        known_constants: Dict of extra constants to include e.g. {"provider": "VNPAY"}.

    Returns:
        Tuple of (parsed_dict or None, error_message or None).
        parsed_dict contains "startRow", "fieldMappings", "confidence", "reasoning".
    """
    if not sample_rows:
        return None, "No sample data rows provided"

    config = AnalysisConfig()
    provider = create_provider(config)

    table = _format_sample_table([headers] + sample_rows)
    candidate_columns = _collect_candidate_columns(headers, sample_rows)
    candidate_hint = ""
    if candidate_columns:
      candidate_hint = "\nCANDIDATE COLUMNS FOR RECONCILIATION (prioritize these before sparse/empty columns):\n"
      for item in candidate_columns[:10]:
          sample_hint = ", ".join(item["sample_values"]) if item["sample_values"] else "no sample values"
          candidate_hint += f"- Column {item['index']}: {item['header']} (non-empty rows: {item['non_empty_count']}; samples: {sample_hint})\n"

    constants_hint = ""
    if known_constants:
        constants_hint = "\nKNOWN CONSTANTS (inject these):\n"
        for k, v in known_constants.items():
            constants_hint += f"  extra.{k} = \"{v}\"\n"
        constants_hint += "Set currency = \"VND\" as CONSTANT.\n"

    user_prompt = f"""Partner: {partner}

Sample data (headers row + {len(sample_rows)} data rows):

{constants_hint}
{candidate_hint}
--- DATA TABLE ---
Row 1 (headers): {headers}
{sample_rows[:10] if len(str(sample_rows)) > 1000 else table}

Analyze the column structure and generate a MappingConfig.

Absolute file positions:
- Header row index: {header_row_index or 1}
- First data row index: {first_data_row_index or 2}
- startRow MUST be the absolute 1-based row index of the first actual data row."""

    user_prompt += """

DATE DETECTION RULES:
- If a date column contains slashes like 2024/07/08 or 2024/07/08 09:11:02,
  still map it as DATE.
- Prefer the most likely transaction date column even if it is not ISO formatted.
- If multiple columns look date-like, choose the one that appears in every row.
"""

    try:
        response = await provider.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
        )
    except Exception as e:
        return None, f"LLM call failed: {e}"

    if not response:
        return None, "LLM returned empty response"

    try:
        parsed = _parse_ai_response(response)
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"Failed to parse LLM JSON response: {e}"

    if not isinstance(parsed, dict):
        return None, f"LLM returned non-object: {type(parsed).__name__}"

    if "fieldMappings" not in parsed:
        return None, "LLM response missing fieldMappings"

    try:
        parsed["fieldMappings"] = _build_field_mappings(parsed["fieldMappings"])
    except Exception as e:
        return None, f"Failed to build field mappings: {e}"

    parsed = _refine_generated_mapping(
        parsed,
        headers=headers,
        sample_rows=sample_rows,
        first_data_row_index=first_data_row_index,
    )

    return parsed, None
