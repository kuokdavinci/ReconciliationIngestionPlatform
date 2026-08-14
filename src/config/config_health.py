"""Configuration health decisions and compatibility wrappers.

Review artifacts are application concerns.  This module keeps the health
decision API used by ingestion while delegating proposal and packet creation
to :mod:`src.application.review.proposal_creation`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.application.review.proposal_creation import (
    ConfigurationApprovalRequiredError,
    CopilotActionRepository,
    ReviewPacketRepository,
    SAMPLE_SIZE,
    candidate_source_paths,
    collect_review_sample_rows,
    create_scheduled_mapping_proposal,
    create_stream_scope_review_packet as create_stream_scope_review_packet_application,
    review_sample_preview,
)
from src.config.loader import ConfigLoader
from src.config.settings import settings
from src.config.signature import (
    StructureSignature,
    compute_signature,
    structure_signatures_equivalent,
)
from src.core.enums import FileType
from src.reconciliation.scope import classify_scope

logger = logging.getLogger(__name__)

ERROR_RATE_THRESHOLD = 0.20


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
    config_repo: Any,
    config_version: Optional[str] = None,
    source_file_name: Optional[str] = None,
    source_file_id: Optional[str] = None,
    source_file_path: Optional[str] = None,
    reconciliation_date: Optional[datetime] = None,
    raw_stage_key: Optional[str] = None,
    backfill_run_id: Optional[str] = None,
) -> Any:
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
        reason=(
            "No approved config found"
            if config is None
            else "Detected stale or changed file structure"
        ),
        source_file_name=source_file_name,
        source_file_id=source_file_id,
        source_file_path=source_file_path,
        reconciliation_date=reconciliation_date,
        raw_stage_key=raw_stage_key,
        backfill_run_id=backfill_run_id,
    )

    if backfill_run_id is not None:
        raise ConfigurationApprovalRequiredError(
            f"Configuration approval required for {partner}",
            proposal_id=str(proposal.id),
            action_id=str(action.id),
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
    active_runtime_config: Any,
    source_file_name: str,
    source_file_path: str | None,
    reconciliation_date: datetime,
    raw_stage_key: str,
    backfill_run_id: str | None = None,
) -> Any:
    """Delegate staged-stream packet construction to the review application."""
    return await create_stream_scope_review_packet_application(
        database=database,
        partner=partner,
        file_type=file_type,
        active_runtime_config=active_runtime_config,
        source_file_name=source_file_name,
        source_file_path=source_file_path,
        reconciliation_date=reconciliation_date,
        raw_stage_key=raw_stage_key,
        backfill_run_id=backfill_run_id,
        packet_repo=ReviewPacketRepository(database),
        scope_classifier=classify_scope,
    )


async def record_config_run_health(
    config_repo: Any,
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
    query: dict[str, Any] = {
        "partner": partner,
        "workflowType": workflow_type,
        "fileType": file_type.value,
        "status": "APPROVED",
    }
    if config_version is not None:
        query["configVersion"] = config_version
    return query


async def _attach_signature(
    config: Any,
    config_repo: Any,
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


def _has_no_signature(config: Any) -> bool:
    return getattr(config, "structure_signature", None) is None


async def _create_mapping_proposal(
    sig: StructureSignature,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_repo: Any,
    action_repo: Any,
    config_version: Optional[str],
    reason: str,
    source_file_name: Optional[str] = None,
    source_file_id: Optional[str] = None,
    source_file_path: Optional[str] = None,
    reconciliation_date: Optional[datetime] = None,
    raw_stage_key: Optional[str] = None,
    backfill_run_id: Optional[str] = None,
) -> tuple[Any, Any]:
    """Compatibility facade for callers that imported the old private helper."""
    return await create_scheduled_mapping_proposal(
        sig=sig,
        partner=partner,
        workflow_type=workflow_type,
        file_type=file_type,
        config_repo=config_repo,
        action_repo=action_repo,
        config_version=config_version,
        reason=reason,
        source_file_name=source_file_name,
        source_file_id=source_file_id,
        source_file_path=source_file_path,
        reconciliation_date=reconciliation_date,
        raw_stage_key=raw_stage_key,
        backfill_run_id=backfill_run_id,
        packet_repo=ReviewPacketRepository(config_repo.collection.database),
        scope_classifier=classify_scope,
    )


def _review_sample_preview(sample_rows: list[list[str]]) -> list[dict[str, Any]]:
    """Compatibility wrapper for the application-owned sample serializer."""
    return review_sample_preview(sample_rows)


def _candidate_source_paths(path: str) -> list[Path]:
    """Compatibility wrapper for shared source path resolution."""
    return candidate_source_paths(path)


async def _collect_review_sample_rows(
    *,
    database: Any,
    partner: str,
    reconciliation_date: Optional[datetime],
    current_file_path: Optional[str],
    current_rows: list[list[str]],
    raw_stage_key: Optional[str] = None,
) -> list[list[str]]:
    """Compatibility wrapper for shared bounded review evidence collection."""
    return await collect_review_sample_rows(
        database=database,
        partner=partner,
        reconciliation_date=reconciliation_date,
        current_file_path=current_file_path,
        current_rows=current_rows,
        raw_stage_key=raw_stage_key,
    )


def _is_config_stale(config: Any, sig: StructureSignature) -> bool:
    config_sig = getattr(config, "structure_signature", None) or {}
    config_health = getattr(config, "config_health", None) or {}
    if bool(config_health.get("stale")):
        return True

    configured_hash = config_sig.get("hash")
    if configured_hash:
        return configured_hash != sig.hash
    return not structure_signatures_equivalent(config_sig, sig)


__all__ = [
    "ConfigurationApprovalRequiredError",
    "check_and_refresh_config",
    "create_stream_scope_review_packet",
    "record_config_run_health",
]
