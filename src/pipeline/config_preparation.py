"""Mapping configuration preparation for ingestion."""

import copy
from typing import Any, Optional

from src.config.config_health import (
    ConfigurationApprovalRequiredError,
    check_and_refresh_config,
)
from src.config.loader import ConfigLoader
from src.core.date_templates import interpolate_date
from src.domain.ingestion.ports import MappingConfigRepositoryPort
from src.domain.mapping.models import MappingConfig
from src.logging import StructuredLogger


class ConfigPreparationService:
    """Resolve mapping config, health checks and date-based sheet names."""

    def __init__(
        self,
        config_loader: ConfigLoader,
        mapping_repository: MappingConfigRepositoryPort,
        logger: StructuredLogger,
    ) -> None:
        self._config_loader = config_loader
        self._mapping_repository = mapping_repository
        self._logger = logger

    async def prepare(
        self,
        *,
        file_path: str,
        file_name: str,
        partner: str,
        workflow_type: str,
        file_type: Any,
        reconciliation_date: Any,
        config_version: Optional[str],
        source_file_id: str,
        enable_health_check: bool,
        mapping_repository: MappingConfigRepositoryPort | None = None,
    ) -> MappingConfig:
        mapping_repository = mapping_repository or self._mapping_repository
        config = None
        if enable_health_check:
            try:
                config = await check_and_refresh_config(
                    file_path=file_path,
                    partner=partner,
                    workflow_type=workflow_type,
                    file_type=file_type,
                    config_loader=self._config_loader,
                    config_repo=mapping_repository,
                    config_version=config_version,
                    source_file_name=file_name,
                    source_file_id=source_file_id,
                    source_file_path=file_path,
                    reconciliation_date=reconciliation_date,
                )
                self._logger.get_logger().info(f"config_health_check_passed for {partner}")
            except ConfigurationApprovalRequiredError:
                raise
            except Exception as exc:
                self._logger.get_logger().warning(
                    f"Config health check failed for {partner}: {exc} - falling back to normal config loading"
                )

        if config is None:
            config = (
                await self._config_loader.load_by_version(partner, config_version)
                if config_version is not None
                else await self._config_loader.load_by_partner_type(partner, workflow_type, file_type)
            )

        if config.sheet_name and "{" in config.sheet_name:
            config = copy.copy(config)
            config.sheet_name = interpolate_date(config.sheet_name, reconciliation_date)
        return config
