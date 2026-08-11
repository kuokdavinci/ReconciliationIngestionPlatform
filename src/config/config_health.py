"""Config health detection that creates approval-gated proposals."""

import logging
import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.signature import StructureSignature, compute_signature, read_raw_rows
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.domain.review.models import (
    CopilotAction,
    CopilotActionType,
)
from src.infrastructure.review.repository import CopilotActionRepository
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.infrastructure.mapping.config_repository import MappingConfigRepository
from src.domain.review.models import (
    ReviewPacket,
    ReviewPacketStatus,
    ReviewPacketSourceType,
)
from src.infrastructure.review.repository import ReviewPacketRepository
from src.reconciliation.scope import classify_scope
from src.services.review_evidence import build_internal_review_evidence

logger = logging.getLogger(__name__)

ERROR_RATE_THRESHOLD = 0.20
SAMPLE_SIZE = 10
REVIEW_SAMPLE_ROW_LIMIT = 100


async def _find_pending_stage_packet(
    packet_repo: ReviewPacketRepository,
    *,
    partner: str,
    raw_stage_key: Optional[str],
    file_type: FileType,
):
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


def _compute_error_rate(total_rows: int, failed_rows: int) -> float:
    if total_rows == 0:
        return 0.0
    return failed_rows / total_rows


async def check_and_refresh_config(
    file_path: str | Path,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_loader: ConfigLoader,
    config_repo: MappingConfigRepository,
    config_version: Optional[str] = None,
    source_file_name: Optional[str] = None,
    source_file_id: Optional[str] = None,
    source_file_path: Optional[str] = None,
    reconciliation_date: Optional[datetime] = None,
    raw_stage_key: Optional[str] = None,
) -> MappingConfig:
    """Detect stale config and create a pending proposal without changing runtime."""
    sig = compute_signature(file_path, sample_size=SAMPLE_SIZE)
    action_repo = CopilotActionRepository(config_repo.collection.database)

    try:
        if config_version is not None:
            config = await config_loader.load_by_version(partner, config_version)
        else:
            config = await config_loader.load_by_partner_type(
                partner, workflow_type, file_type
            )
    except Exception:
        logger.warning("No approved config found for %s", partner)
        config = None

    if raw_stage_key is None and source_file_id:
        try:
            source_doc = await config_repo.collection.database["reconciliation_file"].find_one(
                {"_id": source_file_id}, projection={"fetchUnitMetadata": 1}
            )
            raw_stage_key = (source_doc or {}).get("fetchUnitMetadata", {}).get("rawStageKey")
        except Exception:
            raw_stage_key = None

    if config is not None and _has_no_signature(config):
        await _attach_signature(
            config=config,
            config_repo=config_repo,
            sig=sig,
            partner=partner,
            workflow_type=workflow_type,
            file_type=file_type,
            config_version=config_version,
        )
        return config

    if config is not None and not _is_config_stale(config, sig):
        return config

    proposal, action = await _create_mapping_proposal(
        sig=sig,
        partner=partner,
        workflow_type=workflow_type,
        file_type=file_type,
        config_repo=config_repo,
        action_repo=action_repo,
        config_version=config_version,
        reason="No approved config found" if config is None else "Detected stale or changed file structure",
        source_file_name=source_file_name,
        source_file_id=source_file_id,
        source_file_path=source_file_path,
        reconciliation_date=reconciliation_date,
        raw_stage_key=raw_stage_key,
    )

    if config is not None or not settings.strict_mapping_approval_enabled:
        return config

    raise ConfigurationApprovalRequiredError(
        f"Configuration approval required for {partner}",
        proposal_id=str(proposal.id),
        action_id=str(action.id),
    )


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
) -> ReviewPacket:
    """Create or refresh the human scope gate for one staged API stream."""
    packet_repo = ReviewPacketRepository(database)
    existing = await _find_pending_stage_packet(
        packet_repo,
        partner=partner,
        raw_stage_key=raw_stage_key,
        file_type=file_type,
    )
    signature = compute_signature(source_file_path or "", sample_size=SAMPLE_SIZE)
    sample_rows = await _collect_review_sample_rows(
        database=database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        current_file_path=source_file_path,
        current_rows=signature.sample_rows,
        raw_stage_key=raw_stage_key,
    )
    signature_payload = signature.to_dict()
    signature_payload["sampleRows"] = sample_rows
    scope_meta = await classify_scope(
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
    fields = {
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
        "samplePreview": _review_sample_preview(sample_rows),
        "internalRecordCount": internal_evidence["recordCount"],
        "internalPreview": internal_evidence["sample"],
        "riskSummary": {
            "severity": "medium",
            "summary": "Scope must be confirmed before the paginated stream is reconciled.",
        },
        "runtimeDecisionHint": "APPROVE_CURRENT_MAPPING_FOR_STAGED_STREAM",
    }
    if existing is not None:
        await packet_repo.update_one(
            {"_id": str(existing.id), "status": ReviewPacketStatus.PENDING.value}, fields
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


async def record_config_run_health(
    config_repo: MappingConfigRepository,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_version: Optional[str],
    total_rows: int,
    failed_rows: int,
) -> float:
    error_rate = _compute_error_rate(total_rows, failed_rows)
    stale = error_rate >= ERROR_RATE_THRESHOLD
    query = _config_query(partner, workflow_type, file_type, config_version)
    doc = await config_repo.collection.find_one(query)
    if doc and doc.get("configHealth") is None:
        await config_repo.collection.update_one(query, {"$set": {"configHealth": {}}})

    await config_repo.collection.update_one(
        query,
        {
            "$set": {
                "configHealth.lastRunTotalRows": total_rows,
                "configHealth.lastRunFailedRows": failed_rows,
                "configHealth.lastRunErrorRate": error_rate,
                "configHealth.stale": stale,
                "configHealth.updatedAt": datetime.now(timezone.utc),
            }
        },
    )
    return error_rate


def _config_query(
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_version: Optional[str],
) -> dict[str, Any]:
    query = {
        "partner": partner,
        "workflowType": workflow_type,
        "fileType": file_type.value,
        "status": MappingConfigStatus.APPROVED.value,
    }
    if config_version is not None:
        query["configVersion"] = config_version
    return query


async def _attach_signature(
    config: MappingConfig,
    config_repo: MappingConfigRepository,
    sig: StructureSignature,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_version: Optional[str],
) -> None:
    sig_dict = sig.to_dict()
    config.structure_signature = sig_dict
    query = _config_query(partner, workflow_type, file_type, config_version)
    doc = await config_repo.collection.find_one(query)
    if doc and doc.get("configHealth") is None:
        await config_repo.collection.update_one(query, {"$set": {"configHealth": {}}})

    await config_repo.collection.update_one(
        query,
        {
            "$set": {
                "structureSignature": sig_dict,
                "configHealth.stale": False,
                "configHealth.signatureBootstrappedAt": datetime.now(timezone.utc),
            }
        },
    )


def _has_no_signature(config: MappingConfig) -> bool:
    return getattr(config, "structure_signature", None) is None


async def _create_mapping_proposal(
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
) -> tuple[MappingConfig, CopilotAction]:
    packet_repo = ReviewPacketRepository(config_repo.collection.database)
    sample_rows = await _collect_review_sample_rows(
        database=config_repo.collection.database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        current_file_path=source_file_path,
        current_rows=sig.sample_rows,
        raw_stage_key=raw_stage_key,
    )
    signature_payload = sig.to_dict()
    # The structure hash still comes from the current source unit, while the
    # review evidence includes all available pages for this partner/date.
    signature_payload["sampleRows"] = sample_rows
    scope_meta = await classify_scope(
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
                    ReviewPacket(
                        sourceType=ReviewPacketSourceType.SCHEDULER_JOB,
                        partner=partner,
                        fileName=source_file_name or f"{partner.lower()}-scheduled-fetch",
                        fileTypeDetected=file_type.value,
                        structureSignature=signature_payload,
                        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
                        proposalConfigId=str(existing_pending.id),
                        targetActionId=str(existing_action.id),
                        sourceFileId=source_file_id,
                        sourceFilePath=source_file_path,
                        rawStageKey=raw_stage_key,
                        reconciliationDate=reconciliation_date,
                        scopeType=scope_meta["scopeType"],
                        scopeConfidence=scope_meta["scopeConfidence"],
                        scopeReason=scope_meta["scopeReason"],
                        scopeSignals=scope_meta["scopeSignals"],
                        recommendedAction={
                            "actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME" if active_runtime else "APPROVE_REQUIRED_BEFORE_RUNTIME",
                            "reason": reason,
                            "confidence": float(existing_pending.config_health.get("confidence") or 0.0) if existing_pending.config_health else 0.0,
                        },
                        parseStrategy={
                            "sheetName": existing_pending.sheet_name,
                            "startRow": existing_pending.start_row,
                            "fieldMappingCount": len(existing_pending.field_mappings),
                            "strategy": "AI inferred parser from scheduled partner fetch sample",
                        },
                        validationGates=[
                            {
                                "gateKey": "proposal_reused",
                                "label": "Existing pending proposal reused",
                                "status": "warn" if active_runtime else "fail",
                                "reason": "A pending proposal already existed; this job is surfacing it for review.",
                            },
                        ],
                        samplePreview=_review_sample_preview(sample_rows),
                        internalRecordCount=internal_evidence["recordCount"],
                        internalPreview=internal_evidence["sample"],
                        riskSummary={
                            "severity": "medium" if active_runtime else "high",
                            "summary": reason,
                        },
                        runtimeDecisionHint="KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" if active_runtime else "BLOCK_UNTIL_APPROVED",
                    )
                )
            else:
                # A pending proposal can be reused by multiple scheduled files.
                # Keep the review packet attached to the latest file so scope
                # analysis can exclude the current source file from its DB key
                # comparison and approval reprocessing uses the right payload.
                await packet_repo.update_one(
                    {"_id": str(existing_packet.id), "status": ReviewPacketStatus.PENDING.value},
                    {
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
                        "samplePreview": _review_sample_preview(sample_rows),
                        "internalRecordCount": internal_evidence["recordCount"],
                        "internalPreview": internal_evidence["sample"],
                        "riskSummary": {
                            "severity": "medium",
                            "summary": reason,
                        },
                        "draftMappingId": str(existing_pending.id),
                        "targetActionId": str(existing_action.id),
                    },
                )
            return existing_pending, existing_action

    # A retry can race the first Airflow attempt while its pending mapping
    # proposal is being persisted. Reuse the packet already attached to this
    # stable staged stream instead of creating a second proposal/packet pair.
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
                    {
                        "_id": str(proposal_id),
                        "status": MappingConfigStatus.PENDING_APPROVAL.value,
                    }
                )
                reused_action = await action_repo.find_one({"_id": str(action_id)})
                if reused_proposal is not None and reused_action is not None:
                    await packet_repo.update_one(
                        {"_id": str(staged_packet.id), "status": ReviewPacketStatus.PENDING.value},
                        {
                            "structureSignature": signature_payload,
                            "sourceFileId": source_file_id,
                            "sourceFilePath": source_file_path,
                            "rawStageKey": raw_stage_key,
                            "reconciliationDate": reconciliation_date,
                            "internalRecordCount": internal_evidence["recordCount"],
                            "internalPreview": internal_evidence["sample"],
                        },
                    )
                    return reused_proposal, reused_action

    if not sig.sample_rows:
        raise ConfigurationApprovalRequiredError(
            f"Configuration approval required for {partner}; no sample rows available"
        )

    # Optimization: Defer LLM generation to when operator clicks "Review" in front-end
    result = {
        "sheetName": "Sheet1",
        "startRow": sig.first_data_row_index or 2,
        "fieldMappings": [],
        "confidence": 0.0,
        "reasoning": "AI generation deferred until review modal is opened by user."
    }
    proposal = MappingConfig(
        partner=partner,
        workflowType=workflow_type,
        fileType=file_type,
        sheetName=result.get("sheetName") or "Sheet1",
        startRow=result.get("startRow", 1),
        fieldMappings=result.get("fieldMappings", []),
        configVersion=config_version,
        structureSignature=signature_payload,
        status=MappingConfigStatus.PENDING_APPROVAL,
        configHealth={
            "stale": True,
            "status": "PENDING_APPROVAL",
            "source": "ai_generated",
            "confidence": float(result.get("confidence") or 0.0),
            "reasoning": result.get("reasoning"),
            "updatedAt": datetime.now(timezone.utc),
        },
    )

    validation_errors = []
    if proposal.field_mappings:
        validation_errors = ConfigValidator().validate(proposal)
    if validation_errors:
        raise ConfigurationApprovalRequiredError(
            f"Configuration approval required for {partner}; AI proposal failed validation"
        )

    await config_repo.create(proposal)
    action = CopilotAction(
        type=CopilotActionType.MAPPING_PROPOSAL,
        partner=partner,
        workflowType=workflow_type,
        fileType=file_type,
        targetConfigId=str(proposal.id),
        payload={
            "proposedMappings": [
                fm.model_dump(by_alias=True) if hasattr(fm, "model_dump") else fm
                for fm in proposal.field_mappings
            ],
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "structureSignature": signature_payload,
            "confidence": float(result.get("confidence") or 0.0),
            "reasoning": result.get("reasoning"),
        },
        reason=reason,
    )
    await action_repo.create(action)
    active_runtime = await config_repo.find_by_partner_and_type(
        partner, workflow_type, file_type
    )
    validation_gates = [
        {
            "gateKey": "structure_signature",
            "label": "Structure drift detected",
            "status": "warn" if active_runtime is None else "warn",
            "reason": reason,
        },
        {
            "gateKey": "proposal_generated",
            "label": "Proposal generated",
            "status": "pass",
            "reason": "AI generated a candidate parsing strategy and field mapping set.",
        },
    ]
    packet = ReviewPacket(
        sourceType=ReviewPacketSourceType.SCHEDULER_JOB,
        partner=partner,
        fileName=source_file_name or f"{partner.lower()}-scheduled-fetch",
        fileTypeDetected=file_type.value,
        structureSignature=signature_payload,
        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
        proposalConfigId=str(proposal.id),
        targetActionId=str(action.id),
        sourceFileId=source_file_id,
        sourceFilePath=source_file_path,
        rawStageKey=raw_stage_key,
        reconciliationDate=reconciliation_date,
        scopeType=scope_meta["scopeType"],
        scopeConfidence=scope_meta["scopeConfidence"],
        scopeReason=scope_meta["scopeReason"],
        scopeSignals=scope_meta["scopeSignals"],
        recommendedAction={
            "actionType": "APPROVE_AND_ACTIVATE_NEXT_RUNTIME" if active_runtime else "APPROVE_REQUIRED_BEFORE_RUNTIME",
            "reason": reason,
            "confidence": float(result.get("confidence") or 0.0),
        },
        parseStrategy={
            "sheetName": proposal.sheet_name,
            "startRow": proposal.start_row,
            "fieldMappingCount": len(proposal.field_mappings),
            "strategy": "AI inferred parser from scheduled partner fetch sample",
        },
        validationGates=validation_gates,
        samplePreview=_review_sample_preview(sample_rows),
        internalRecordCount=internal_evidence["recordCount"],
        internalPreview=internal_evidence["sample"],
        riskSummary={
            "severity": "medium" if active_runtime else "high",
            "summary": reason,
        },
        runtimeDecisionHint="KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" if active_runtime else "BLOCK_UNTIL_APPROVED",
    )
    await packet_repo.create(packet)
    return proposal, action


def _review_sample_preview(sample_rows: list[list[str]]) -> list[dict[str, Any]]:
    """Serialize the complete bounded sample used by the review desk."""
    return [
        {"rowIndex": idx + 1, "values": row}
        for idx, row in enumerate(sample_rows)
    ]


def _candidate_source_paths(path: str) -> list[Path]:
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


async def _collect_review_sample_rows(
    *,
    database: Any,
    partner: str,
    reconciliation_date: Optional[datetime],
    current_file_path: Optional[str],
    current_rows: list[list[str]],
    raw_stage_key: Optional[str] = None,
) -> list[list[str]]:
    """Collect distinct rows from all persisted source pages for one run date.

    A paginated API source creates one ``reconciliation_file`` document per
    page.  Using only the current page made a packet created on page 3 show
    two rows even though pages 1 and 2 were already persisted.  The packet is
    bounded to avoid turning review metadata into an unbounded data store.
    """
    query: dict[str, Any] = {"partner": partner}
    if reconciliation_date is not None:
        query["reconciliationDate"] = reconciliation_date

    paths: list[str] = []
    metadata_samples: list[Any] = []
    try:
        collection = database["reconciliation_file"]
        cursor = collection.find(
            query,
            projection={"fetchUnitMetadata": 1, "createdAt": 1},
        ).sort("createdAt", 1)
        documents = await cursor.to_list(length=None)
        for document in documents:
            metadata = document.get("fetchUnitMetadata") or {}
            if isinstance(metadata.get("sampleRows"), list):
                metadata_samples.append(metadata["sampleRows"])
            path = metadata.get("localPath")
            if isinstance(path, str) and path and path not in paths:
                paths.append(path)
    except Exception:
        # Packet creation must remain best-effort if a legacy database lacks
        # source-file metadata; the current page sample is still valid.
        documents = []

    # Paginated API pages are staged before the first page reaches config
    # health. Include their bounded samples in the same review evidence.
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
        # Older deployments may not have the staging collection yet.
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
            return [
                [str(item.get(header, "")) for header in headers]
                for item in raw_rows
            ]
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
        resolved = next((item for item in _candidate_source_paths(path) if item.is_file()), None)
        if resolved is None:
            continue
        try:
            add_rows(read_raw_rows(resolved, max_rows=REVIEW_SAMPLE_ROW_LIMIT))
        except (OSError, ValueError):
            continue

    # The current signature is already in memory and remains the fallback when
    # cleanup or a container volume prevents reading older page files.
    add_rows(current_rows)
    return rows[:REVIEW_SAMPLE_ROW_LIMIT]


def _is_config_stale(config: MappingConfig, sig: StructureSignature) -> bool:
    config_sig = getattr(config, "structure_signature", None) or {}
    config_health = getattr(config, "config_health", None) or {}
    return (
        config_sig.get("hash") != sig.hash
        or bool(config_health.get("stale"))
    )
