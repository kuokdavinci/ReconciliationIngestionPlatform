"""Application-owned builders for mapping proposals and review packets."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.signature import (
    StructureSignature,
    read_raw_rows,
)
from src.core.enums import FileType
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.review.models import (
    CopilotAction,
    CopilotActionStatus,
    CopilotActionType,
    ReviewPacket,
    ReviewPacketSourceType,
    ReviewPacketStatus,
)
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.infrastructure.review.repository import (
    CopilotActionRepository,
    ReviewPacketRepository,
)
from src.reconciliation.scope import classify_scope
from src.application.review.evidence import build_internal_review_evidence


SAMPLE_SIZE = 10
REVIEW_SAMPLE_ROW_LIMIT = 100


class ConfigurationApprovalRequiredError(Exception):
    """Raised when ingestion must stop until a human approves a config."""

    def __init__(
        self,
        message: str,
        proposal_id: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.proposal_id = proposal_id
        self.action_id = action_id


def build_review_packet(
    *,
    source_type: str,
    partner: str,
    file_name: str,
    file_type: FileType,
    fields: dict[str, Any],
) -> ReviewPacket:
    """Build a review packet while preserving source-specific metadata."""
    packet_fields: dict[str, Any] = {
        "sourceType": source_type,
        "partner": partner,
        "fileName": file_name,
        "fileTypeDetected": file_type.value,
        **fields,
    }
    return ReviewPacket(**packet_fields)


def build_source_file_action(
    *,
    partner: str,
    proposal: MappingConfig,
    field_mappings: list[dict[str, Any]],
    confidence: float,
    reasoning: str,
    headers: list[str],
    sample_rows: list[list[str]],
) -> CopilotAction:
    """Build the upload-generated action while keeping mapping metadata stable."""
    return CopilotAction(
        type=CopilotActionType.MAPPING_PROPOSAL,
        status=CopilotActionStatus.PENDING_APPROVAL,
        partner=partner,
        workflowType="UPC",
        fileType=FileType.SETTLEMENT,
        draftMappingId=str(proposal.id),
        payload={
            "proposedMappings": field_mappings,
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "confidence": confidence,
            "reasoning": reasoning,
            "headers": headers,
            "sampleRows": sample_rows[:10],
        },
        reason="Generated from source file for review",
    )


def build_source_file_review_packet(
    *,
    command: Any,
    proposal: MappingConfig,
    action: CopilotAction,
    active_runtime: MappingConfig | None,
    scope_meta: dict[str, Any],
    field_mappings: list[dict[str, Any]],
    signature: StructureSignature,
    confidence: float,
    recommended_action_type: str,
    recommended_reason: str,
    validation_gates: list[dict[str, Any]],
) -> ReviewPacket:
    """Build the upload packet through the same application-owned artifact layer."""
    return ReviewPacket(
        sourceType=ReviewPacketSourceType(command.source_type),
        partner=command.partner,
        fileName=command.source_file_path.name,
        fileTypeDetected=FileType.SETTLEMENT.value,
        structureSignature=proposal.structure_signature,
        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
        draftMappingId=str(proposal.id),
        targetActionId=str(action.id),
        sourceFileId=str(command.source_file.id) if command.source_file is not None else None,
        sourceFilePath=str(command.source_file_path),
        scopeType=scope_meta["scopeType"],
        scopeConfidence=scope_meta["scopeConfidence"],
        scopeReason=scope_meta["scopeReason"],
        scopeSignals=scope_meta["scopeSignals"],
        recommendedAction={
            "actionType": recommended_action_type,
            "reason": recommended_reason,
            "confidence": confidence,
        },
        parseStrategy={
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "fieldMappingCount": len(field_mappings),
            "strategy": "AI inferred spreadsheet draft mapping",
        },
        validationGates=validation_gates,
        samplePreview=[
            {"rowIndex": index + 1, "values": row}
            for index, row in enumerate(signature.sample_rows[:5])
        ],
        riskSummary={
            "severity": "high" if not active_runtime else "medium",
            "summary": recommended_reason,
        },
        runtimeDecisionHint=(
            "KEEP_CURRENT_RUNTIME_UNTIL_APPROVED"
            if active_runtime
            else "BLOCK_UNTIL_APPROVED"
        ),
    )


async def _find_pending_stage_packet(
    packet_repo: ReviewPacketRepository,
    *,
    partner: str,
    raw_stage_key: Optional[str],
    file_type: FileType,
) -> ReviewPacket | None:
    """Read the idempotent packet key when the repository supports it."""
    if not raw_stage_key:
        return None
    finder = getattr(packet_repo, "find_latest_pending_by_stage", None)
    if not callable(finder):
        return None
    result = finder(
        partner=partner,
        raw_stage_key=raw_stage_key,
        file_type=file_type.value,
    )
    if not inspect.isawaitable(result):
        return None
    return await result


async def create_stream_scope_review_packet(
    *,
    database: Any,
    partner: str,
    file_type: FileType,
    active_runtime_config: MappingConfig,
    source_file_name: str,
    source_file_path: str | None,
    reconciliation_date: datetime,
    raw_stage_key: str,
    backfill_run_id: str | None = None,
    packet_repo: ReviewPacketRepository | None = None,
    scope_classifier: Callable[..., Any] = classify_scope,
) -> ReviewPacket:
    """Create or refresh the human scope gate for one staged API stream."""
    packet_repo = packet_repo or ReviewPacketRepository(database)
    existing = await _find_pending_stage_packet(
        packet_repo,
        partner=partner,
        raw_stage_key=raw_stage_key,
        file_type=file_type,
    )
    signature = _compute_signature(source_file_path or "")
    sample_rows = await collect_review_sample_rows(
        database=database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        current_file_path=source_file_path,
        current_rows=signature.sample_rows,
        raw_stage_key=raw_stage_key,
    )
    signature_payload = signature.to_dict()
    signature_payload["sampleRows"] = sample_rows
    scope_meta = await scope_classifier(
        database,
        partner=partner,
        reconciliation_date=reconciliation_date,
    )
    internal_evidence = await build_internal_review_evidence(
        database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        record_count=(scope_meta.get("scopeSignals") or {}).get("internalDbRecordCount"),
    )
    fields: dict[str, Any] = {
        "fileName": source_file_name,
        "structureSignature": signature_payload,
        "activeRuntimeConfigId": str(active_runtime_config.id),
        "sourceFilePath": source_file_path,
        "rawStageKey": raw_stage_key,
        "reconciliationDate": reconciliation_date,
        "scopeType": scope_meta["scopeType"],
        "scopeConfidence": scope_meta["scopeConfidence"],
        "scopeReason": scope_meta["scopeReason"],
        "scopeSignals": scope_meta["scopeSignals"],
        "recommendedAction": {
            "actionType": "APPROVE_KEEP_CURRENT_FOR_FILE",
            "reason": "A complete paginated API stream requires a scope decision before one logical reconciliation batch is created.",
            "confidence": 1.0,
        },
        "parseStrategy": {
            "sheetName": active_runtime_config.sheet_name,
            "startRow": active_runtime_config.start_row,
            "fieldMappingCount": len(active_runtime_config.field_mappings),
            "workflowType": active_runtime_config.workflow_type,
            "strategy": "Approved runtime mapping; operator scope review required for staged stream.",
        },
        "validationGates": [],
        "samplePreview": review_sample_preview(sample_rows),
        "internalRecordCount": internal_evidence["recordCount"],
        "internalPreview": internal_evidence["sample"],
        "riskSummary": {
            "severity": "medium",
            "summary": "Scope must be confirmed before the paginated stream is reconciled.",
        },
        "runtimeDecisionHint": "APPROVE_CURRENT_MAPPING_FOR_STAGED_STREAM",
    }
    if backfill_run_id is not None:
        fields["backfillRunId"] = backfill_run_id
    if existing is not None:
        await packet_repo.update_one(
            {"_id": str(existing.id), "status": ReviewPacketStatus.PENDING.value},
            fields,
        )
        return existing
    packet = ReviewPacket(
        sourceType=ReviewPacketSourceType.SCHEDULER_JOB,
        partner=partner,
        fileName=source_file_name,
        fileTypeDetected=file_type.value,
        **fields,
    )
    await packet_repo.create(packet)
    return packet


async def create_scheduled_mapping_proposal(
    *,
    sig: StructureSignature,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_repo: MappingConfigRepository,
    action_repo: CopilotActionRepository,
    config_version: Optional[str],
    reason: str,
    source_file_name: Optional[str] = None,
    source_file_id: Optional[str] = None,
    source_file_path: Optional[str] = None,
    reconciliation_date: Optional[datetime] = None,
    raw_stage_key: Optional[str] = None,
    backfill_run_id: Optional[str] = None,
    packet_repo: ReviewPacketRepository | None = None,
    scope_classifier: Callable[..., Any] = classify_scope,
) -> tuple[MappingConfig, CopilotAction]:
    """Create or reuse the scheduled proposal/action/packet bundle."""
    database: Any = config_repo.collection.database
    packet_repo = packet_repo or ReviewPacketRepository(database)
    sample_rows = await collect_review_sample_rows(
        database=config_repo.collection.database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        current_file_path=source_file_path,
        current_rows=sig.sample_rows,
        raw_stage_key=raw_stage_key,
    )
    signature_payload = sig.to_dict()
    signature_payload["sampleRows"] = sample_rows
    scope_meta = await scope_classifier(
        config_repo.collection.database,
        partner=partner,
        reconciliation_date=reconciliation_date,
    )
    internal_evidence = await build_internal_review_evidence(
        config_repo.collection.database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        record_count=(scope_meta.get("scopeSignals") or {}).get("internalDbRecordCount"),
    )
    existing_pending = await config_repo.find_latest_pending_by_partner_and_type(
        partner, workflow_type, file_type
    )
    if existing_pending is not None:
        existing_action = await action_repo.find_one(
            {
                "targetConfigId": str(existing_pending.id),
                "type": CopilotActionType.MAPPING_PROPOSAL.value,
            }
        )
        if existing_action is not None:
            existing_packet = await packet_repo.find_latest_by_proposal(str(existing_pending.id))
            if existing_packet is None:
                existing_packet = await _find_pending_stage_packet(
                    packet_repo,
                    partner=partner,
                    raw_stage_key=raw_stage_key,
                    file_type=file_type,
                )
            if existing_packet is None:
                active_runtime = await config_repo.find_by_partner_and_type(
                    partner, workflow_type, file_type
                )
                await packet_repo.create(
                    _build_scheduled_packet(
                        partner=partner,
                        file_type=file_type,
                        source_file_name=source_file_name,
                        signature_payload=signature_payload,
                        active_runtime=active_runtime,
                        proposal=existing_pending,
                        action=existing_action,
                        backfill_run_id=backfill_run_id,
                        source_file_id=source_file_id,
                        source_file_path=source_file_path,
                        raw_stage_key=raw_stage_key,
                        reconciliation_date=reconciliation_date,
                        scope_meta=scope_meta,
                        sample_rows=sample_rows,
                        internal_evidence=internal_evidence,
                        reason=reason,
                        reused=True,
                    )
                )
            else:
                packet_update: dict[str, Any] = {
                    "fileName": source_file_name or f"{partner.lower()}-scheduled-fetch",
                    "structureSignature": signature_payload,
                    "sourceFileId": source_file_id,
                    "sourceFilePath": source_file_path,
                    "rawStageKey": raw_stage_key,
                    "reconciliationDate": reconciliation_date,
                    "scopeType": scope_meta["scopeType"],
                    "scopeConfidence": scope_meta["scopeConfidence"],
                    "scopeReason": scope_meta["scopeReason"],
                    "scopeSignals": scope_meta["scopeSignals"],
                    "samplePreview": review_sample_preview(sample_rows),
                    "internalRecordCount": internal_evidence["recordCount"],
                    "internalPreview": internal_evidence["sample"],
                    "riskSummary": {"severity": "medium", "summary": reason},
                    "draftMappingId": str(existing_pending.id),
                    "targetActionId": str(existing_action.id),
                }
                if backfill_run_id is not None:
                    packet_update["backfillRunId"] = backfill_run_id
                await packet_repo.update_one(
                    {"_id": str(existing_packet.id), "status": ReviewPacketStatus.PENDING.value},
                    packet_update,
                )
            return existing_pending, existing_action

    if existing_pending is None:
        staged_packet = await _find_pending_stage_packet(
            packet_repo,
            partner=partner,
            raw_stage_key=raw_stage_key,
            file_type=file_type,
        )
        if staged_packet is not None:
            proposal_id = getattr(staged_packet, "draft_mapping_id", None)
            action_id = getattr(staged_packet, "target_action_id", None)
            if proposal_id and action_id:
                reused_proposal = await config_repo.find_one(
                    {"_id": str(proposal_id), "status": MappingConfigStatus.PENDING_APPROVAL.value}
                )
                reused_action = await action_repo.find_one({"_id": str(action_id)})
                if reused_proposal is not None and reused_action is not None:
                    packet_update = {
                        "structureSignature": signature_payload,
                        "sourceFileId": source_file_id,
                        "sourceFilePath": source_file_path,
                        "rawStageKey": raw_stage_key,
                        "reconciliationDate": reconciliation_date,
                        "internalRecordCount": internal_evidence["recordCount"],
                        "internalPreview": internal_evidence["sample"],
                    }
                    if backfill_run_id is not None:
                        packet_update["backfillRunId"] = backfill_run_id
                    await packet_repo.update_one(
                        {"_id": str(staged_packet.id), "status": ReviewPacketStatus.PENDING.value},
                        packet_update,
                    )
                    return reused_proposal, reused_action

    if not sig.sample_rows:
        raise ConfigurationApprovalRequiredError(
            f"Configuration approval required for {partner}; no sample rows available"
        )

    result: dict[str, Any] = {
        "sheetName": "Sheet1",
        "startRow": sig.first_data_row_index or 2,
        "fieldMappings": [],
        "confidence": 0.0,
        "reasoning": "AI generation deferred until review modal is opened by user.",
    }
    proposal = MappingConfig(
        partner=partner,
        workflowType=workflow_type,
        fileType=file_type,
        sheetName=result["sheetName"],
        startRow=result["startRow"],
        fieldMappings=[],
        configVersion=config_version,
        structureSignature=signature_payload,
        status=MappingConfigStatus.PENDING_APPROVAL,
        configHealth={
            "stale": True,
            "status": MappingConfigStatus.PENDING_APPROVAL.value,
            "source": "ai_generated",
            "confidence": 0.0,
            "reasoning": result["reasoning"],
            "updatedAt": datetime.now(timezone.utc),
        },
    )
    await config_repo.create(proposal)
    action_fields: dict[str, Any] = {
        "type": CopilotActionType.MAPPING_PROPOSAL,
        "partner": partner,
        "workflowType": workflow_type,
        "fileType": file_type,
        "targetConfigId": str(proposal.id),
        "payload": {
            "proposedMappings": [],
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "structureSignature": signature_payload,
            "confidence": 0.0,
            "reasoning": result["reasoning"],
        },
        "reason": reason,
    }
    action = CopilotAction(**action_fields)
    await action_repo.create(action)
    active_runtime = await config_repo.find_by_partner_and_type(partner, workflow_type, file_type)
    packet = _build_scheduled_packet(
        partner=partner,
        file_type=file_type,
        source_file_name=source_file_name,
        signature_payload=signature_payload,
        active_runtime=active_runtime,
        proposal=proposal,
        action=action,
        backfill_run_id=backfill_run_id,
        source_file_id=source_file_id,
        source_file_path=source_file_path,
        raw_stage_key=raw_stage_key,
        reconciliation_date=reconciliation_date,
        scope_meta=scope_meta,
        sample_rows=sample_rows,
        internal_evidence=internal_evidence,
        reason=reason,
    )
    await packet_repo.create(packet)
    return proposal, action


def _build_scheduled_packet(
    *,
    partner: str,
    file_type: FileType,
    source_file_name: str | None,
    signature_payload: dict[str, Any],
    active_runtime: MappingConfig | None,
    proposal: MappingConfig,
    action: CopilotAction,
    backfill_run_id: str | None,
    source_file_id: str | None,
    source_file_path: str | None,
    raw_stage_key: str | None,
    reconciliation_date: datetime | None,
    scope_meta: dict[str, Any],
    sample_rows: list[list[str]],
    internal_evidence: dict[str, Any],
    reason: str,
    reused: bool = False,
) -> ReviewPacket:
    confidence = float((proposal.config_health or {}).get("confidence") or 0.0)
    packet_fields: dict[str, Any] = {
        "structureSignature": signature_payload,
        "activeRuntimeConfigId": str(active_runtime.id) if active_runtime else None,
        "proposalConfigId": str(proposal.id),
        "targetActionId": str(action.id),
        "backfillRunId": backfill_run_id,
        "sourceFileId": source_file_id,
        "sourceFilePath": source_file_path,
        "rawStageKey": raw_stage_key,
        "reconciliationDate": reconciliation_date,
        "scopeType": scope_meta["scopeType"],
        "scopeConfidence": scope_meta["scopeConfidence"],
        "scopeReason": scope_meta["scopeReason"],
        "scopeSignals": scope_meta["scopeSignals"],
        "recommendedAction": {
            "actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME" if active_runtime else "APPROVE_REQUIRED_BEFORE_RUNTIME",
            "reason": reason,
            "confidence": confidence,
        },
        "parseStrategy": {
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "fieldMappingCount": len(proposal.field_mappings),
            "strategy": "AI inferred parser from scheduled partner fetch sample",
        },
        "validationGates": [
            {
                "gateKey": "proposal_reused" if reused else "proposal_generated",
                "label": "Existing pending proposal reused" if reused else "Proposal generated",
                "status": "warn" if reused and active_runtime else ("fail" if reused else "pass"),
                "reason": (
                    "A pending proposal already existed; this job is surfacing it for review."
                    if reused
                    else "AI generated a candidate parsing strategy and field mapping set."
                ),
            }
        ],
        "samplePreview": review_sample_preview(sample_rows),
        "internalRecordCount": internal_evidence["recordCount"],
        "internalPreview": internal_evidence["sample"],
        "riskSummary": {"severity": "medium" if active_runtime else "high", "summary": reason},
        "runtimeDecisionHint": (
            "KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" if active_runtime else "BLOCK_UNTIL_APPROVED"
        ),
    }
    return build_review_packet(
        source_type=ReviewPacketSourceType.SCHEDULER_JOB.value,
        partner=partner,
        file_name=source_file_name or f"{partner.lower()}-scheduled-fetch",
        file_type=file_type,
        fields=packet_fields,
    )


def _compute_signature(path: str) -> StructureSignature:
    from src.config.signature import compute_signature

    return compute_signature(path, sample_size=SAMPLE_SIZE)


def review_sample_preview(sample_rows: list[list[str]]) -> list[dict[str, Any]]:
    """Serialize the bounded sample used by the review desk."""
    return [{"rowIndex": idx + 1, "values": row} for idx, row in enumerate(sample_rows)]


def candidate_source_paths(path: str) -> list[Path]:
    """Resolve shared Docker volume paths from API and Airflow containers."""
    candidate = Path(path)
    if candidate.is_absolute():
        return [candidate]
    return [
        candidate,
        Path.cwd() / candidate,
        Path("/opt/airflow/app") / candidate,
        Path("/app") / candidate,
    ]


async def collect_review_sample_rows(
    *,
    database: Any,
    partner: str,
    reconciliation_date: Optional[datetime],
    current_file_path: Optional[str],
    current_rows: list[list[str]],
    raw_stage_key: Optional[str] = None,
) -> list[list[str]]:
    """Collect distinct bounded rows from persisted files and raw API pages."""
    query: dict[str, Any] = {"partner": partner}
    if reconciliation_date is not None:
        query["reconciliationDate"] = reconciliation_date

    paths: list[str] = []
    metadata_samples: list[Any] = []
    try:
        cursor = database["reconciliation_file"].find(
            query,
            projection={"fetchUnitMetadata": 1, "createdAt": 1},
        ).sort("createdAt", 1)
        for document in await cursor.to_list(length=None):
            metadata = document.get("fetchUnitMetadata") or {}
            if isinstance(metadata.get("sampleRows"), list):
                metadata_samples.append(metadata["sampleRows"])
            path = metadata.get("localPath")
            if isinstance(path, str) and path and path not in paths:
                paths.append(path)
    except Exception:
        pass

    try:
        raw_query: dict[str, Any] = {
            "partner": partner,
            "status": {"$in": ["STAGED", "CONSUMED"]},
        }
        if raw_stage_key:
            raw_query["stageKey"] = raw_stage_key
        if reconciliation_date is not None:
            raw_query["reconciliationDate"] = reconciliation_date
        raw_cursor = database["raw_ingestion_page"].find(
            raw_query,
            projection={"sampleRows": 1, "page": 1},
        ).sort("page", 1)
        for document in await raw_cursor.to_list(length=None):
            sample = document.get("sampleRows")
            if isinstance(sample, list):
                metadata_samples.append(sample)
    except Exception:
        pass

    if current_file_path and current_file_path not in paths:
        paths.append(current_file_path)

    rows: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def add_rows(candidate_rows: list[list[str]]) -> None:
        for row in candidate_rows:
            normalized = [str(value) for value in row]
            key = tuple(normalized)
            if key in seen:
                continue
            seen.add(key)
            rows.append(normalized)
            if len(rows) >= REVIEW_SAMPLE_ROW_LIMIT:
                return

    def normalize_metadata_rows(raw_rows: Any) -> list[list[str]]:
        if not isinstance(raw_rows, list):
            return []
        if all(isinstance(item, dict) for item in raw_rows):
            headers: list[str] = []
            for item in raw_rows:
                for key in item:
                    if key not in headers:
                        headers.append(str(key))
            return [[str(item.get(header, "")) for header in headers] for item in raw_rows]
        return [
            [str(value) for value in item]
            for item in raw_rows
            if isinstance(item, (list, tuple))
        ]

    for raw_rows in metadata_samples:
        add_rows(normalize_metadata_rows(raw_rows))
    for path in paths:
        if len(rows) >= REVIEW_SAMPLE_ROW_LIMIT:
            break
        resolved = next((item for item in candidate_source_paths(path) if item.is_file()), None)
        if resolved is None:
            continue
        try:
            add_rows(read_raw_rows(resolved, max_rows=REVIEW_SAMPLE_ROW_LIMIT))
        except (OSError, ValueError):
            continue
    add_rows(current_rows)
    return rows[:REVIEW_SAMPLE_ROW_LIMIT]
