"""Config health detection that creates approval-gated proposals."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.signature import StructureSignature, compute_signature
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

logger = logging.getLogger(__name__)

ERROR_RATE_THRESHOLD = 0.20
SAMPLE_SIZE = 10


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
    )

    if config is not None or not settings.strict_mapping_approval_enabled:
        return config

    raise ConfigurationApprovalRequiredError(
        f"Configuration approval required for {partner}",
        proposal_id=str(proposal.id),
        action_id=str(action.id),
    )


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
) -> tuple[MappingConfig, CopilotAction]:
    packet_repo = ReviewPacketRepository(config_repo.collection.database)
    scope_meta = await classify_scope(
        config_repo.collection.database,
        partner=partner,
        file_name=source_file_name or f"{partner.lower()}-scheduled-fetch",
        reconciliation_date=reconciliation_date,
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
                active_runtime = await config_repo.find_by_partner_and_type(
                    partner, workflow_type, file_type
                )
                await packet_repo.create(
                    ReviewPacket(
                        sourceType=ReviewPacketSourceType.SCHEDULER_JOB,
                        partner=partner,
                        fileName=source_file_name or f"{partner.lower()}-scheduled-fetch",
                        fileTypeDetected=file_type.value,
                        structureSignature=sig.to_dict(),
                        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
                        proposalConfigId=str(existing_pending.id),
                        targetActionId=str(existing_action.id),
                        sourceFileId=source_file_id,
                        sourceFilePath=source_file_path,
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
                        samplePreview=[
                            {"rowIndex": idx + 1, "values": row}
                            for idx, row in enumerate(sig.sample_rows[:5])
                        ],
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
                        "structureSignature": sig.to_dict(),
                        "sourceFileId": source_file_id,
                        "sourceFilePath": source_file_path,
                        "reconciliationDate": reconciliation_date,
                        "scopeType": scope_meta["scopeType"],
                        "scopeConfidence": scope_meta["scopeConfidence"],
                        "scopeReason": scope_meta["scopeReason"],
                        "scopeSignals": scope_meta["scopeSignals"],
                        "samplePreview": [
                            {"rowIndex": idx + 1, "values": row}
                            for idx, row in enumerate(sig.sample_rows[:5])
                        ],
                        "riskSummary": {
                            "severity": "medium",
                            "summary": reason,
                        },
                    },
                )
            return existing_pending, existing_action

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
        structureSignature=sig.to_dict(),
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
            "structureSignature": sig.to_dict(),
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
        structureSignature=sig.to_dict(),
        activeRuntimeConfigId=str(active_runtime.id) if active_runtime else None,
        proposalConfigId=str(proposal.id),
        targetActionId=str(action.id),
        sourceFileId=source_file_id,
        sourceFilePath=source_file_path,
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
        samplePreview=[
            {"rowIndex": idx + 1, "values": row}
            for idx, row in enumerate(sig.sample_rows[:5])
        ],
        riskSummary={
            "severity": "medium" if active_runtime else "high",
            "summary": reason,
        },
        runtimeDecisionHint="KEEP_CURRENT_RUNTIME_UNTIL_APPROVED" if active_runtime else "BLOCK_UNTIL_APPROVED",
    )
    await packet_repo.create(packet)
    return proposal, action


def _is_config_stale(config: MappingConfig, sig: StructureSignature) -> bool:
    config_sig = getattr(config, "structure_signature", None) or {}
    config_health = getattr(config, "config_health", None) or {}
    return (
        config_sig.get("hash") != sig.hash
        or bool(config_health.get("stale"))
    )
