"""Application service for mapping configuration state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.application.mapping.errors import MappingConflictError, MappingNotFoundError
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.review.models import CopilotActionStatus, ReviewPacketStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApproveMappingCommand:
    config_id: str
    actor: str | None
    confidence: float | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class RejectMappingCommand:
    config_id: str
    actor: str | None


@dataclass(frozen=True)
class SaveMappingCommand:
    config: MappingConfig
    actor: str | None = None


@dataclass(frozen=True)
class MappingMutationResult:
    config: MappingConfig
    status: MappingConfigStatus
    message: str | None = None


class MappingApplicationService:
    """Own mapping transitions while keeping persistence behind named ports."""

    def __init__(
        self,
        *,
        mapping_repo,
        action_repo,
        review_packet_repo,
        audit_recorder: Callable[..., Awaitable[Any]],
        cache_invalidator: Callable[[str, str], Awaitable[Any]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.mapping_repo = mapping_repo
        self.action_repo = action_repo
        self.review_packet_repo = review_packet_repo
        self.audit_recorder = audit_recorder
        self.cache_invalidator = cache_invalidator
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def approve(self, command: ApproveMappingCommand) -> MappingMutationResult:
        config = await self.mapping_repo.find_one({"_id": command.config_id})
        if config is None:
            raise MappingNotFoundError("Mapping config not found.")
        if config.status is not MappingConfigStatus.PENDING_APPROVAL:
            raise MappingConflictError("Only pending configs can be approved.")

        now = self.clock()
        current_approved = await self.mapping_repo.find_by_partner_and_type(
            config.partner,
            config.workflow_type,
            config.file_type,
        )
        if current_approved is not None:
            await self.mapping_repo.mark_superseded(
                str(current_approved.id),
                str(config.id),
                now,
            )

        health = dict(config.config_health or {})
        health.update(
            {
                "stale": False,
                "status": MappingConfigStatus.APPROVED.value,
                "approvedAt": now,
            }
        )
        if command.confidence is not None:
            health["confidence"] = command.confidence
        if command.reasoning is not None:
            health["reasoning"] = command.reasoning

        await self.mapping_repo.mark_approved(
            command.config_id,
            now,
            command.actor,
            health,
        )
        await self.action_repo.sync_mapping_status(
            command.config_id,
            CopilotActionStatus.APPROVED,
            command.actor,
            now,
        )
        await self.review_packet_repo.sync_mapping_status(
            command.config_id,
            ReviewPacketStatus.APPROVED,
            now,
        )

        config.status = MappingConfigStatus.APPROVED
        config.approved_at = now
        config.approved_by = command.actor
        config.config_health = health
        await self._invalidate_cache(config.partner)
        await self._audit(config, "APPROVED", command.actor)
        return MappingMutationResult(config=config, status=config.status)

    async def reject(self, command: RejectMappingCommand) -> MappingMutationResult:
        config = await self.mapping_repo.find_one({"_id": command.config_id})
        if config is None:
            raise MappingNotFoundError("Mapping config not found.")
        if config.status is not MappingConfigStatus.PENDING_APPROVAL:
            raise MappingConflictError("Only pending configs can be rejected.")

        now = self.clock()
        health = dict(config.config_health or {})
        health["status"] = MappingConfigStatus.REJECTED.value
        await self.mapping_repo.mark_rejected(command.config_id, health)
        await self.action_repo.sync_mapping_status(
            command.config_id,
            CopilotActionStatus.REJECTED,
            command.actor,
            now,
        )
        await self.review_packet_repo.sync_mapping_status(
            command.config_id,
            ReviewPacketStatus.REJECTED,
            now,
        )

        config.status = MappingConfigStatus.REJECTED
        config.config_health = health
        await self._audit(config, "REJECTED", command.actor)
        return MappingMutationResult(config=config, status=config.status)

    async def save(self, command: SaveMappingCommand) -> MappingMutationResult:
        config = command.config
        query = {
            "partner": config.partner,
            "workflowType": config.workflow_type,
            "fileType": config.file_type.value,
            "status": MappingConfigStatus.APPROVED.value,
        }
        existing = await self.mapping_repo.find_one(query)
        if not config.config_version or config.config_version in {
            "v_manual",
            "v_ai_generated",
            "latest",
        }:
            config.config_version = await self.mapping_repo.allocate_next_version(config.partner)

        now = self.clock()
        config.status = MappingConfigStatus.APPROVED
        config.approved_at = now
        config.approved_by = command.actor
        config.config_health = {
            "stale": False,
            "status": MappingConfigStatus.APPROVED.value,
            "approvedAt": now,
            "confidence": 1.0,
            "reasoning": "Manually saved by administrator.",
        }

        if existing is not None:
            config.id = existing.id
            await self.mapping_repo.replace_approved(config)
            message = "Mapping config updated successfully."
        else:
            await self.mapping_repo.insert_approved(config)
            message = "Mapping config created successfully."

        await self._invalidate_cache(config.partner)
        return MappingMutationResult(config=config, status=config.status, message=message)

    async def _invalidate_cache(self, partner: str) -> None:
        try:
            await self.cache_invalidator(partner, "")
        except Exception as exc:  # cache refresh must not block a persisted transition
            logger.error("Failed to invalidate insight cache for %s: %s", partner, exc)

    async def _audit(
        self,
        config: MappingConfig,
        action: str,
        actor: str | None,
    ) -> None:
        reference = config.config_version or str(config.id)
        await self.audit_recorder(
            entity_type="MAPPING_CONFIG",
            entity_id=str(config.id),
            action=action,
            actor=actor,
            metadata={
                "partner": config.partner,
                "reference": reference,
                "mappingVersion": reference,
                "status": config.status.value,
            },
        )
