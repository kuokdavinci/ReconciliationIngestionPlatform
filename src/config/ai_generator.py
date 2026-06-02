"""AI-powered MappingConfig generator.

Uses LLM to analyze sample data from a reconciliation file and produce
a MappingConfig (field mappings, start row, mappings) automatically.
Falls back gracefully if LLM is unavailable.
"""

import json
import logging
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
- CONSTANT: always the same literal value (e.g., currency = "VND")
- MAPPING: status values needing translation (e.g., "SUCCESS" -> "SUCCESS", "FAILED" -> "FAILED")

CANONICAL FIELDS (must map all that are present):
- id (STRING, required): unique transaction identifier
- trace (STRING): partner transaction ID used as reconciliation key
- amount (DECIMAL): transaction amount
- currency (CONSTANT): always "VND" for Vietnamese partners
- status (MAPPING): transaction status with value mapping
- transDate (DATE): transaction date
- extra.service (CONSTANT): set to "PAYMENT" unless evidence shows otherwise
- extra.portal (CONSTANT): portal/platform name
- extra.provider (CONSTANT): partner/provider name

COLUMN REFERENCE: column numbers are 1-based (column 1 = first column).

MAPPING RULE: for status fields, provide a mapping dictionary that maps 
each observed status value to SUCCESS, FAILED, PENDING, or REVERSED.

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
                kwargs["constant"] = fm["constant"]
            else:
                kwargs["column"] = fm.get("column")
                if ftype == FieldMappingType.MAPPING:
                    kwargs["mapping"] = fm.get("mapping", {})
            result.append(FieldMapping(**kwargs))
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping invalid field mapping: {fm} — {e}")
    return result


async def generate_config_from_samples(
    partner: str,
    headers: list[str],
    sample_rows: list[list[str]],
    *,
    known_constants: Optional[dict[str, str]] = None,
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

    constants_hint = ""
    if known_constants:
        constants_hint = "\nKNOWN CONSTANTS (inject these):\n"
        for k, v in known_constants.items():
            constants_hint += f"  extra.{k} = \"{v}\"\n"
        constants_hint += "Set currency = \"VND\" as CONSTANT.\n"

    user_prompt = f"""Partner: {partner}

Sample data (headers row + {len(sample_rows)} data rows):

{constants_hint}
--- DATA TABLE ---
Row 1 (headers): {headers}
{sample_rows[:10] if len(str(sample_rows)) > 1000 else table}

Analyze the column structure and generate a MappingConfig."""

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

    return parsed, None
