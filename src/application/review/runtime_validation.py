"""Service for performing runtime validation on draft configurations."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from src.infrastructure.review.repository import ReviewPacketRepository
from src.normalizer.normalizer import TransactionNormalizer
from src.readers import create_reader
from src.application.review.raw_stream import (
    iter_review_stream_records,
    resolve_review_source_file,
)


def serialize_runtime_value(value: Any) -> Any:
    """Serialize values specifically for runtime trace payloads."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def runtime_error_code(field: Optional[str], reason: Optional[str]) -> str:
    """Determine a standardized API error code from normalizer/validator exceptions."""
    text = str(reason or "").lower()
    field_name = str(field or "").lower()
    if "sourcefield '" in text and "not found" in text:
        return "SOURCE_FIELD_NOT_FOUND"
    if text.startswith("column ") and " not found" in text:
        return "COLUMN_NOT_FOUND"
    if "out of range" in text or "invalid column letter" in text:
        return "COLUMN_OUT_OF_RANGE"
    if "required field '" in text and "not found in normalized data" in text:
        return "MISSING_REQUIRED_FIELD"
    if "value is none" in text or "source field value is none" in text or "cannot map empty/null value" in text:
        return "VALUE_IS_NULL"
    if "invalid decimal value" in text or "float not allowed for monetary values" in text:
        return "INVALID_DECIMAL"
    if "invalid date value" in text or "expected string or datetime" in text:
        return "INVALID_DATE"
    if "unmapped value" in text:
        return "UNMAPPED_VALUE"
    if "mapping dict not configured" in text or "constant value is not configured" in text or "no column configured" in text:
        return "MAPPING_RULE_MISSING"
    if "invalid status value" in text:
        return "INVALID_CANONICAL_STATUS"
    if "unknown mapping type" in text:
        return "UNKNOWN_MAPPING_TYPE"
    if field_name in {"id", "amount", "currency", "status"} and "required field" in text:
        return "MISSING_REQUIRED_FIELD"
    return "CANONICAL_BUILD_FAILED"


def runtime_trace_status(error_code: Optional[str]) -> str:
    """Determine status level (warning vs error vs ok) based on error code."""
    if error_code:
        if error_code in {"VALUE_IS_NULL", "UNMAPPED_VALUE"}:
            return "warning"
        return "error"
    return "ok"


def serialize_runtime_trace(row_number: int, traces: list, normalized_data: dict, build_errors: Optional[list] = None) -> dict:
    """Format row traces and normalization errors for endpoint consumption."""
    return {
        "row": row_number,
        "normalizedData": {
            key: serialize_runtime_value(val)
            for key, val in normalized_data.items()
        },
        "fieldTraces": [
            {
                "path": trace.path,
                "type": trace.mapping_type,
                "column": trace.column,
                "sourceField": trace.source_field,
                "sourceValue": serialize_runtime_value(trace.source_value),
                "outputValue": serialize_runtime_value(trace.output_value),
                "status": runtime_trace_status(
                    runtime_error_code(trace.error.field, trace.error.reason) if trace.error else None
                ),
                "errorCode": runtime_error_code(trace.error.field, trace.error.reason) if trace.error else None,
                "errorMessage": trace.error.reason if trace.error else None,
            }
            for trace in traces
        ],
        "buildErrors": [
            {
                "field": err.field,
                "reason": err.reason,
                "row": err.row,
                "errorCode": runtime_error_code(err.field, err.reason),
            }
            for err in (build_errors or [])
        ],
    }


def upsert_validation_gate(packet, gate: dict) -> list[dict]:
    """Upsert a validation gate to the packet's gate list, replacing any old one with the same key."""
    gates = [dict(item) for item in (packet.validation_gates or []) if item.get("gateKey") != gate["gateKey"]]
    gates.append(gate)
    return gates


def derive_validation_state(gate: dict) -> str:
    details = gate.get("details") or {}
    status = str(gate.get("status", "")).lower()
    success_rate = details.get("successRate")
    validated_mapping_version = details.get("validatedMappingVersion")
    current_mapping_version = details.get("currentMappingVersion")
    if (
        validated_mapping_version
        and current_mapping_version
        and validated_mapping_version != current_mapping_version
    ):
        return "STALE"
    if status == "pass":
        if isinstance(success_rate, (int, float)) and success_rate < 1:
            return "PASSED_WITH_WARNINGS"
        return "CURRENT"
    if status == "fail":
        return "FAILED"
    return "NOT_RUN"


async def run_runtime_validation(db, packet, config) -> dict:
    """Execute dry-run runtime validation using Excel file or sample previews."""
    source_file_path = getattr(packet, "source_file_path", None)
    validated_at = datetime.now(timezone.utc)
    validated_mapping_version = getattr(config, "config_version", None) or str(getattr(config, "id", ""))
    current_mapping_version = validated_mapping_version
    sampled_rows = 0
    success_rows = 0
    failed_rows = 0
    failed_examples: list[dict] = []
    trace_samples: list[dict] = []
    if not config.field_mappings:
        return {
            "gateKey": "runtime_validation",
            "status": "fail",
            "message": "Draft mapping configuration has no field mappings defined.",
            "details": {
                "validatedAt": validated_at.isoformat(),
                "validatedMappingVersion": validated_mapping_version,
                "currentMappingVersion": current_mapping_version,
                "sampledRows": 0,
                "successRows": 0,
                "failedRows": 0,
                "successRate": 0.0,
                "failedExamples": [{"error": "Empty field mappings"}],
                "topIssues": [{"code": "EMPTY_MAPPINGS", "count": 1, "message": "Draft mapping configuration has no field mappings defined."}],
                "fieldResults": [],
                "traceSamples": [],
            },
        }

    normalizer = TransactionNormalizer(config.field_mappings)
    preserves_object_rows = any(
        getattr(mapping, "sourceField", None)
        for mapping in config.field_mappings
        if str(getattr(mapping, "type", "")).upper() != "CONSTANT"
    )

    def _consume_row(row: Any, row_number: int) -> None:
        nonlocal sampled_rows, success_rows, failed_rows, failed_examples, trace_samples
        sampled_rows += 1
        norm_result, field_traces = normalizer.normalize_with_trace(row, row_number)
        if norm_result.errors:
            failed_rows += 1
            failed_examples.append({
                "row": row_number,
                "reason": norm_result.errors[0].reason,
                "field": norm_result.errors[0].field,
            })
            if len(trace_samples) < 5:
                trace_samples.append(
                    serialize_runtime_trace(row_number, field_traces, norm_result.data)
                )
            return
        txn, build_errors = TransactionNormalizer.build_canonical(
            norm_result.data, [], row_number
        )
        if txn is None:
            failed_rows += 1
            failed_examples.append({
                "row": row_number,
                "reason": build_errors[0].reason,
                "field": build_errors[0].field,
            })
            if len(trace_samples) < 5:
                trace_samples.append(
                    serialize_runtime_trace(row_number, field_traces, norm_result.data, build_errors)
                )
        else:
            success_rows += 1
            if len(trace_samples) < 5:
                trace_samples.append(
                    serialize_runtime_trace(row_number, field_traces, norm_result.data)
                )

    raw_stage_key = getattr(packet, "raw_stage_key", None)
    if raw_stage_key:
        async for stream_row in iter_review_stream_records(db=db, packet=packet):
            row = stream_row["values"]
            if isinstance(row, dict) and not preserves_object_rows:
                row = list(row.values())
            if not isinstance(row, (dict, list, tuple)):
                row = [row]
            row_number = int(stream_row["streamRowIndex"] or sampled_rows + 1)
            _consume_row(row if isinstance(row, dict) else list(row), row_number)
    elif source_file_path:
        try:
            path = resolve_review_source_file(packet)
        except (FileNotFoundError, ValueError):
            return {
                "gateKey": "runtime_validation",
                "label": "Runtime validation",
                "status": "fail",
                "reason": f"Source file is not available at {source_file_path}.",
                "details": {
                    "successRows": 0,
                    "failedRows": 0,
                    "sampledRows": 0,
                    "validatedAt": validated_at.isoformat(),
                    "validatedMappingVersion": validated_mapping_version,
                    "currentMappingVersion": current_mapping_version,
                    "successRate": 0,
                    "riskLevel": "HIGH",
                },
            }
        with create_reader(path, config) as reader:
            for row in reader.iter_rows():
                row_number = config.start_row + sampled_rows
                _consume_row(row, row_number)
                if sampled_rows >= 20:
                    break
    else:
        sample_preview = getattr(packet, "sample_preview", None) or []
        for idx, sample in enumerate(sample_preview[:20]):
            row = sample.get("values") if isinstance(sample, dict) else None
            if not isinstance(row, list):
                continue
            row_number = int(sample.get("rowIndex") or (config.start_row + idx)) if isinstance(sample, dict) else (config.start_row + idx)
            _consume_row(row, row_number)

        if sampled_rows == 0:
            return {
                "gateKey": "runtime_validation",
                "label": "Runtime validation",
                "status": "fail",
                "reason": "No source file path or sample preview is attached to this review packet.",
                "details": {
                    "successRows": 0,
                    "failedRows": 0,
                    "sampledRows": 0,
                    "validatedAt": validated_at.isoformat(),
                    "validatedMappingVersion": validated_mapping_version,
                    "currentMappingVersion": current_mapping_version,
                    "successRate": 0,
                    "riskLevel": "HIGH",
                },
            }

    if sampled_rows == 0:
        status = "fail"
        reason = "No readable data rows were produced by the proposed mapping."
    elif success_rows == 0:
        status = "fail"
        reason = "The proposed mapping could not normalize any sampled rows."
    elif failed_rows == 0:
        status = "pass"
        reason = f"Validated successfully on {success_rows}/{sampled_rows} sampled rows."
    else:
        success_rate = success_rows / sampled_rows
        status = "pass" if success_rate >= 0.8 else "fail"
        reason = (
            f"Validated {success_rows}/{sampled_rows} sampled rows successfully."
            if status == "pass"
            else f"Only {success_rows}/{sampled_rows} sampled rows normalized successfully."
        )

    success_rate = (success_rows / sampled_rows) if sampled_rows else 0
    risk_level = "LOW" if failed_rows == 0 else ("MEDIUM" if status == "pass" else "HIGH")
    gate = {
        "gateKey": "runtime_validation",
        "label": "Runtime validation",
        "status": status,
        "reason": reason,
        "details": {
            "sampledRows": sampled_rows,
            "successRows": success_rows,
            "failedRows": failed_rows,
            "failedExamples": failed_examples[:3],
            "traceSamples": trace_samples,
            "validatedAt": validated_at.isoformat(),
            "validatedMappingVersion": validated_mapping_version,
            "currentMappingVersion": current_mapping_version,
            "successRate": success_rate,
            "riskLevel": risk_level,
        },
    }
    repo = ReviewPacketRepository(db)
    await repo.collection.update_one(
        {"_id": str(packet.id)},
        {"$set": {"validationGates": upsert_validation_gate(packet, gate)}},
    )
    return gate
