"""ConfigHealthService — detects stale configs and auto-generates new ones.

Orchestrates the full flow:
1. Compute file signature before pipeline runs
2. Compare with stored config signature
3. Check error rate from recent runs
4. If stale → AI-generate new config → validate → save
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config.ai_generator import generate_config_from_samples
from src.config.loader import ConfigLoader
from src.config.signature import StructureSignature, compute_signature
from src.config.validator import ConfigValidator
from src.core.enums import FileType
from src.models.mapping_config import (
    MappingConfig,
    MappingConfigRepository,
)

logger = logging.getLogger(__name__)

ERROR_RATE_THRESHOLD = 0.20  # 20% failure rate triggers re-detect
SAMPLE_SIZE = 10  # number of data rows to send to LLM
AUTO_APPLY_CONFIDENCE_THRESHOLD = 0.85


def _compute_error_rate(
    total_rows: int,
    failed_rows: int,
) -> float:
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
) -> MappingConfig:
    """Check if config is stale and auto-refresh if needed.

    Process:
    1. Compute file structure signature.
    2. Load current config from DB.
    3. If config has a stored signature → compare with file signature.
    4. If config has error rate history from recent runs → check threshold.
    5. If stale (signature mismatch OR error rate > 20%):
       a. Call AIConfigGenerator with sample data.
       b. If AI succeeds → validate, save new config with new signature.
       c. If AI fails → log warning, use existing config.
    6. Return the (possibly refreshed) config.

    Args:
        file_path: Path to the data file.
        partner: Partner identifier.
        workflow_type: Workflow type.
        file_type: File type.
        config_loader: ConfigLoader instance.
        config_repo: MappingConfig repository.
        config_version: Optional config version.

    Returns:
        A validated MappingConfig (possibly freshly generated).
    """
    # 1. Compute signature from file
    sig = compute_signature(file_path, sample_size=SAMPLE_SIZE)

    # 2. Load current config
    try:
        if config_version is not None:
            config = await config_loader.load_by_version(partner, config_version)
        else:
            config = await config_loader.load_by_partner_type(
                partner, workflow_type, file_type
            )
    except Exception:
        logger.warning(
            f"No existing config found for {partner} — will attempt AI generation"
        )
        config = None

    # 3-4. Check if config is stale. If this is an older config without a
    # stored signature, bootstrap the fingerprint and keep using it.
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

    # 5. Stale or no config — try AI generation
    if not sig.sample_rows:
        logger.warning(f"No sample rows to analyze for {partner}")
        if config is not None:
            return config
        raise ValueError(f"No config found for {partner} and no sample data available")

    known_constants = {
        "provider": partner,
    }

    result, error = await generate_config_from_samples(
        partner=partner,
        headers=sig.headers,
        sample_rows=sig.sample_rows,
        known_constants=known_constants,
    )

    if error or result is None:
        logger.error(f"AI config generation failed for {partner}: {error}")
        if config is not None:
            logger.warning(f"Falling back to existing config for {partner}")
            return config
        raise ValueError(
            f"AI config generation failed for {partner} and no fallback config exists"
        )

    confidence = float(result.get("confidence") or 0.0)

    # Low-confidence AI output should not be auto-applied.
    if confidence < AUTO_APPLY_CONFIDENCE_THRESHOLD:
        pending_config = MappingConfig(
            partner=partner,
            workflowType=workflow_type,
            fileType=file_type,
            sheetName=result.get("sheetName") or "Sheet1",
            startRow=result.get("startRow", 1),
            fieldMappings=result.get("fieldMappings", []),
            configVersion=config_version,
            structureSignature=sig.to_dict(),
            configHealth={
                "stale": True,
                "status": "PENDING_REVIEW",
                "source": "ai_generated",
                "confidence": confidence,
                "reasoning": result.get("reasoning"),
                "updatedAt": datetime.now(timezone.utc),
            },
        )
        await _upsert_config(
            config_repo=config_repo,
            config=pending_config,
            partner=partner,
            workflow_type=workflow_type,
            file_type=file_type,
            config_version=config_version,
        )
        logger.info(
            f"AI config for {partner} needs review (confidence={confidence:.2f})"
        )
        return pending_config

    # Build and save new config
    new_config = MappingConfig(
        partner=partner,
        workflowType=workflow_type,
        fileType=file_type,
        sheetName=result.get("sheetName") or "Sheet1",
        startRow=result.get("startRow", 1),
        fieldMappings=result.get("fieldMappings", []),
        configVersion=config_version,
        structureSignature=sig.to_dict(),
        configHealth={
            "stale": False,
            "status": "ACTIVE",
            "source": "ai_generated",
            "confidence": confidence,
            "reasoning": result.get("reasoning"),
            "updatedAt": datetime.now(timezone.utc),
        },
    )

    validator = ConfigValidator()
    validation_errors = validator.validate(new_config)
    if validation_errors:
        logger.error(f"AI-generated config failed validation: {validation_errors}")
        if config is not None:
            return config
        raise ValueError(f"AI-generated config failed validation: {validation_errors}")

    await _upsert_config(
        config_repo=config_repo,
        config=new_config,
        partner=partner,
        workflow_type=workflow_type,
        file_type=file_type,
        config_version=config_version,
    )

    # Invalidate cache so next load picks up the new config
    config_loader.invalidate_cache(
        config_loader._cache_key_version(partner, config_version)
        if config_version
        else config_loader._cache_key_partner_type(partner, workflow_type, file_type)
    )

    logger.info(
        f"AI generated new MappingConfig for {partner} "
        f"(confidence: {result.get('confidence', 'N/A')})"
    )
    return new_config


async def record_config_run_health(
    config_repo: MappingConfigRepository,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_version: Optional[str],
    total_rows: int,
    failed_rows: int,
) -> float:
    """Persist post-run config health based on normalization failure rate.

    High failed-row ratio means the config may still structurally match the
    file, but semantic mapping can be outdated (wrong column, status values,
    date format, etc.). The next health check treats this as stale.
    """
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
    if config_version is not None:
        return {"partner": partner, "configVersion": config_version}
    return {
        "partner": partner,
        "workflowType": workflow_type,
        "fileType": file_type.value,
    }


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


async def _upsert_config(
    config_repo: MappingConfigRepository,
    config: MappingConfig,
    partner: str,
    workflow_type: str,
    file_type: FileType,
    config_version: Optional[str],
) -> None:
    await config_repo.collection.delete_many(
        _config_query(partner, workflow_type, file_type, config_version)
    )
    config_repo._set_model_class(MappingConfig)
    await config_repo.create(config)


def _is_config_stale(config: MappingConfig, sig: StructureSignature) -> bool:
    """Check whether a config is stale compared to the file signature.

    Positive signals (ANY triggers stale):
    1. Config has a stored signature AND it differs from the file's signature.
    2. Config has NO stored signature → assume first-use, not stale.
    """
    health = getattr(config, "config_health", None) or {}
    if health.get("stale") is True:
        logger.info("Config marked stale by previous run health")
        return True

    last_error_rate = health.get("lastRunErrorRate")
    if isinstance(last_error_rate, (int, float)) and last_error_rate >= ERROR_RATE_THRESHOLD:
        logger.info(f"Config stale due to error rate: {last_error_rate:.2%}")
        return True

    stored_sig_raw = getattr(config, "structure_signature", None)
    if not isinstance(stored_sig_raw, dict):
        return False

    stored_sig = StructureSignature.from_dict(stored_sig_raw)

    # Compare hashes — quick check
    if stored_sig.hash != sig.hash:
        logger.info(
            f"Config signature mismatch: stored={stored_sig.hash[:8]} "
            f"vs file={sig.hash[:8]}"
        )
        return True

    # Double-check column count
    if stored_sig.column_count != sig.column_count:
        logger.info(
            f"Column count changed: stored={stored_sig.column_count} "
            f"vs file={sig.column_count}"
        )
        return True

    return False
