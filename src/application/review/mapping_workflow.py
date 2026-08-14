"""Application workflow for mapping generation and review decisions."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from src.application.review.actions import (
    approve_packet_mapping_and_reprocess,
    mark_packet,
    reprocess_packet_with_current_mapping,
    update_packet_scope,
)
from src.application.review.ai_mapping_context import resolve_ai_generation_context
from src.application.review.errors import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewValidationError,
)
from src.application.review.mapping_support import (
    apply_source_reference_strategy,
    has_passing_runtime_gate,
    schedule_in_event_loop,
    serialize_mapping,
    serialize_packet,
)
from src.core.enums import FileType
from src.core.types import FieldMapping
from src.domain.mapping.contract import (
    canonicalize_field_mappings,
    serialize_field_mappings,
    validate_mapping_contract,
)
from src.domain.mapping.models import MappingConfig, MappingConfigStatus
from src.domain.review.models import ReviewDecisionMode, ReviewPacketStatus


class ReviewMappingWorkflow:
    """Own mapping changes made from the approval desk."""

    def __init__(
        self,
        *,
        db,
        packet_repo,
        mapping_repo,
        context_resolver: Callable[..., Awaitable[dict[str, Any]]] = resolve_ai_generation_context,
        config_generator: Callable[..., Awaitable[tuple[dict[str, Any] | None, str | None]]],
        approve_activate_action: Callable[..., Awaitable[dict | None]] = approve_packet_mapping_and_reprocess,
        approve_keep_current_action: Callable[..., Awaitable[dict | None]] = reprocess_packet_with_current_mapping,
        mark_packet: Callable[..., Awaitable[dict]] = mark_packet,
        update_packet_scope: Callable[..., Awaitable[None]] = update_packet_scope,
        schedule_background: Callable[[Awaitable[Any]], None] = schedule_in_event_loop,
        workflow_gateway: Any | None = None,
        packet_serializer: Callable[[Any], dict[str, Any]] = serialize_packet,
        next_version: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self.db = db
        self.packet_repo = packet_repo
        self.mapping_repo = mapping_repo
        self.context_resolver = context_resolver
        self.config_generator = config_generator
        self.approve_activate_action = approve_activate_action
        self.approve_keep_current_action = approve_keep_current_action
        self.mark_packet = mark_packet
        self.update_packet_scope = update_packet_scope
        self.schedule_background = schedule_background
        self.workflow_gateway = workflow_gateway
        self.packet_serializer = packet_serializer
        self.next_version = next_version or mapping_repo.allocate_next_version

    async def generate(self, packet_id: str, *, force: bool = False) -> dict[str, Any]:
        packet = await self._get_pending_packet(packet_id)
        existing = None
        if packet.draft_mapping_id:
            existing = await self.mapping_repo.find_one({"_id": packet.draft_mapping_id})
        if existing is not None and existing.field_mappings and not force:
            return {"ok": True, "mapping": serialize_mapping(existing), "warnings": []}

        context = await self.context_resolver(self.db, packet, existing)
        headers = list(context.get("headers") or [])
        sample_rows = list(context.get("sample_rows") or [])
        if not headers:
            raise ReviewValidationError("No header signature is attached to this review packet.")
        if not sample_rows:
            raise ReviewValidationError("No sample rows are attached to this review packet.")

        config_dict, error = await self.config_generator(
            partner=packet.partner,
            headers=headers,
            sample_rows=sample_rows,
            known_constants={"provider": packet.partner},
            header_row_index=context.get("header_row_index"),
            first_data_row_index=(
                context.get("first_data_row_index")
                or packet.parse_strategy.get("startRow")
                or 2
            ),
        )
        if error or config_dict is None:
            raise ReviewValidationError(f"AI mapping generation failed: {error}")

        field_mappings, mapping_warnings = canonicalize_field_mappings(
            serialize_field_mappings(config_dict.get("fieldMappings") or [])
        )
        field_mappings = apply_source_reference_strategy(
            field_mappings,
            headers=headers,
            source_file_name=packet.source_file_path or packet.file_name,
        )
        file_type = self._file_type(packet.file_type_detected)
        workflow_type = (
            getattr(existing, "workflow_type", None)
            or packet.parse_strategy.get("workflowType")
            or "UPC"
        )
        structure_signature = {
            "headers": headers,
            "sampleRows": sample_rows[:10],
            "headerRowIndex": context.get("header_row_index"),
            "firstDataRowIndex": context.get("first_data_row_index")
            or packet.parse_strategy.get("startRow")
            or 2,
            "columnCount": len(headers),
        }
        now = datetime.now(timezone.utc)
        config_health = {
            "stale": False,
            "status": MappingConfigStatus.PENDING_APPROVAL.value,
            "source": "ai_generated",
            "confidence": config_dict.get("confidence") or 0.85,
            "reasoning": config_dict.get("reasoning")
            or "Automatically generated by AI from review packet samples.",
            "updatedAt": now,
        }
        sheet_name = config_dict.get("sheetName") or packet.parse_strategy.get("sheetName") or "Sheet1"
        start_row = config_dict.get("startRow") or packet.parse_strategy.get("startRow") or 2

        if existing is not None and existing.status == MappingConfigStatus.PENDING_APPROVAL:
            await self._update_pending_draft(
                str(existing.id),
                {
                    "sheetName": sheet_name,
                    "startRow": start_row,
                    "fieldMappings": field_mappings,
                    "structureSignature": structure_signature,
                    "configHealth": config_health,
                    "status": MappingConfigStatus.PENDING_APPROVAL.value,
                    "fileType": file_type.value,
                    "workflowType": workflow_type,
                },
            )
            mapping = existing
            mapping.sheet_name = sheet_name
            mapping.start_row = start_row
            mapping.field_mappings = field_mappings
            mapping.structure_signature = structure_signature
            mapping.config_health = config_health
            mapping.workflow_type = workflow_type
            mapping.file_type = file_type
        else:
            mapping = MappingConfig(
                partner=packet.partner,
                workflowType=workflow_type,
                fileType=file_type,
                sheetName=sheet_name,
                startRow=start_row,
                fieldMappings=[FieldMapping.model_validate(item) for item in field_mappings],
                configVersion=(
                    getattr(existing, "config_version", None)
                    if existing is not None
                    else await self.next_version(packet.partner)
                ),
                structureSignature=structure_signature,
                status=MappingConfigStatus.PENDING_APPROVAL,
                configHealth=config_health,
            )
            await self.mapping_repo.create(mapping)

        validation_gates = [
            dict(gate)
            for gate in (packet.validation_gates or [])
            if gate.get("gateKey") != "runtime_validation"
        ]
        mapping_payload = serialize_mapping(mapping)
        await self._update_packet_draft(
            packet_id=packet_id,
            draft_mapping_id=str(mapping.id),
            draft_mapping_version=mapping_payload["draftMappingVersion"],
            parse_strategy={
                **(packet.parse_strategy or {}),
                "sheetName": sheet_name,
                "startRow": start_row,
                "fieldMappingCount": len(field_mappings),
                "strategy": "AI regenerated draft mapping from review packet samples",
            },
            validation_gates=validation_gates,
        )
        return {
            "ok": True,
            "draftMappingId": str(mapping.id),
            "draftMappingVersion": mapping_payload["draftMappingVersion"],
            "mapping": mapping_payload,
            "warnings": mapping_warnings,
            "validationGates": validation_gates,
        }

    async def save(
        self,
        packet_id: str,
        *,
        field_mappings: list[Any],
        sheet_name: str = "Sheet1",
        start_row: int = 2,
    ) -> dict[str, Any]:
        packet = await self._get_pending_packet(packet_id)
        existing = (
            await self.mapping_repo.find_one({"_id": packet.draft_mapping_id})
            if packet.draft_mapping_id
            else None
        )
        mappings, mapping_warnings = canonicalize_field_mappings(
            serialize_field_mappings(field_mappings)
        )
        file_type = self._file_type(packet.file_type_detected)
        workflow_type = (
            getattr(existing, "workflow_type", None)
            or packet.parse_strategy.get("workflowType")
            or "UPC"
        )
        candidate = MappingConfig(
            partner=packet.partner,
            workflowType=workflow_type,
            fileType=file_type,
            sheetName=sheet_name,
            startRow=start_row,
            fieldMappings=[FieldMapping.model_validate(item) for item in mappings],
            configVersion=getattr(existing, "config_version", None),
            structureSignature=packet.structure_signature
            or getattr(existing, "structure_signature", None),
            status=MappingConfigStatus.PENDING_APPROVAL,
            configHealth={"status": MappingConfigStatus.PENDING_APPROVAL.value},
        )
        validation = validate_mapping_contract(candidate)
        validation_warnings = [
            warning for warning in validation.warnings if warning not in mapping_warnings
        ]
        if validation.errors:
            raise ReviewValidationError(
                "Draft mapping is incomplete or invalid: " + "; ".join(validation.errors)
            )

        now = datetime.now(timezone.utc)
        config_health = {
            "stale": False,
            "status": MappingConfigStatus.PENDING_APPROVAL.value,
            "confidence": 0.95,
            "reasoning": "Updated from Guided Review inline mapping edits.",
            "updatedAt": now,
        }
        if existing is not None:
            await self._update_pending_draft(
                str(existing.id),
                {
                    "sheetName": sheet_name,
                    "startRow": start_row,
                    "fieldMappings": mappings,
                    "status": MappingConfigStatus.PENDING_APPROVAL.value,
                    "configHealth": config_health,
                    "structureSignature": candidate.structure_signature,
                    "workflowType": workflow_type,
                    "fileType": file_type.value,
                },
            )
            draft_id = str(existing.id)
            draft_version = existing.config_version or draft_id
        else:
            candidate.config_version = await self.next_version(packet.partner)
            candidate.config_health = config_health
            await self.mapping_repo.create(candidate)
            draft_id = str(candidate.id)
            draft_version = candidate.config_version or draft_id

        validation_gates = [
            dict(gate)
            for gate in (packet.validation_gates or [])
            if gate.get("gateKey") != "runtime_validation"
        ]
        await self._update_packet_draft(
            packet_id=packet_id,
            draft_mapping_id=draft_id,
            draft_mapping_version=draft_version,
            parse_strategy={
                **(packet.parse_strategy or {}),
                "sheetName": sheet_name,
                "startRow": start_row,
                "fieldMappingCount": len(mappings),
            },
            validation_gates=validation_gates,
        )
        return {
            "ok": True,
            "draftMappingId": draft_id,
            "draftMappingVersion": draft_version,
            "fieldMappingCount": len(mappings),
            "sheetName": sheet_name,
            "startRow": start_row,
            "warnings": mapping_warnings + validation_warnings,
            "validationGates": validation_gates,
        }

    async def approve_activate(
        self,
        packet_id: str,
        *,
        actor: str | None,
        scope_type: str | None = None,
    ) -> dict[str, Any]:
        packet = await self.packet_repo.find_one({"_id": packet_id})
        if packet is None:
            raise ReviewNotFoundError("Review packet not found.")
        already_approved_backfill = (
            packet.status == ReviewPacketStatus.APPROVED
            and packet.decision_mode == ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME
            and bool(packet.backfill_run_id)
        )
        if already_approved_backfill:
            if not has_passing_runtime_gate(packet):
                raise ReviewValidationError("Runtime validation must pass before approval.")
            post_approve_run = await self.approve_activate_action(
                self.db,
                packet,
                actor,
                schedule_background=self.schedule_background,
                workflow_gateway=self.workflow_gateway,
            )
            response = {"ok": True, "packet": self.packet_serializer(packet)}
            if post_approve_run is not None:
                if "backfillRun" in post_approve_run:
                    response["backfillRun"] = post_approve_run["backfillRun"]
                else:
                    response["postApproveRun"] = post_approve_run
            return response
        if packet.status != ReviewPacketStatus.PENDING:
            raise ReviewConflictError("Only pending review packets can be processed.")
        if not has_passing_runtime_gate(packet):
            raise ReviewValidationError("Runtime validation must pass before approval.")
        await self.update_packet_scope(self.db, packet_id, packet, scope_type)
        post_approve_run = await self.approve_activate_action(
            self.db,
            packet,
            actor,
            schedule_background=self.schedule_background,
            workflow_gateway=self.workflow_gateway,
        )
        response = await self.mark_packet(
            self.db,
            packet_id,
            ReviewPacketStatus.APPROVED,
            ReviewDecisionMode.APPROVE_ACTIVATE_NEXT_RUNTIME,
            actor,
            self.packet_serializer,
        )
        if post_approve_run is not None:
            if "backfillRun" in post_approve_run:
                response["backfillRun"] = post_approve_run["backfillRun"]
            else:
                response["postApproveRun"] = post_approve_run
        return response

    async def approve_keep_current(
        self,
        packet_id: str,
        *,
        actor: str | None,
        scope_type: str | None = None,
    ) -> dict[str, Any]:
        packet = await self._get_pending_packet(packet_id)
        if not has_passing_runtime_gate(packet):
            raise ReviewValidationError("Runtime validation must pass before approval.")
        await self.update_packet_scope(self.db, packet_id, packet, scope_type)
        post_approve_run = await self.approve_keep_current_action(
            self.db,
            packet,
            actor,
            schedule_background=self.schedule_background,
        )
        response = await self.mark_packet(
            self.db,
            packet_id,
            ReviewPacketStatus.APPROVED,
            ReviewDecisionMode.APPROVE_KEEP_CURRENT_FOR_FILE,
            actor,
            self.packet_serializer,
        )
        if post_approve_run is not None:
            response["postApproveRun"] = post_approve_run
        return response

    async def reject(self, packet_id: str, *, actor: str | None) -> dict[str, Any]:
        await self._get_pending_packet(packet_id)
        return await self.mark_packet(
            self.db,
            packet_id,
            ReviewPacketStatus.REJECTED,
            ReviewDecisionMode.REJECT,
            actor,
            self.packet_serializer,
        )

    async def _get_pending_packet(self, packet_id: str):
        packet = await self.packet_repo.find_one({"_id": packet_id})
        if packet is None:
            raise ReviewNotFoundError("Review packet not found.")
        if packet.status != ReviewPacketStatus.PENDING:
            raise ReviewConflictError("Only pending review packets can be processed.")
        return packet

    async def _update_pending_draft(self, config_id: str, updates: dict[str, Any]) -> None:
        method = getattr(self.mapping_repo, "update_pending_draft", None)
        if method is not None and inspect.iscoroutinefunction(method):
            await method(config_id, updates)
            return
        collection = getattr(self.mapping_repo, "collection", None)
        if collection is None:
            raise RuntimeError("Mapping repository cannot update a pending draft.")
        result = collection.update_one(
            {"_id": str(config_id), "status": MappingConfigStatus.PENDING_APPROVAL.value},
            {"$set": updates},
        )
        if inspect.isawaitable(result):
            await result

    async def _update_packet_draft(
        self,
        *,
        packet_id: str,
        draft_mapping_id: str,
        draft_mapping_version: str,
        parse_strategy: dict,
        validation_gates: list[dict],
    ) -> None:
        method = getattr(self.packet_repo, "update_mapping_draft", None)
        if method is not None and inspect.iscoroutinefunction(method):
            await method(
                packet_id=packet_id,
                draft_mapping_id=draft_mapping_id,
                draft_mapping_version=draft_mapping_version,
                parse_strategy=parse_strategy,
                validation_gates=validation_gates,
            )
            return
        collection = getattr(self.packet_repo, "collection", None)
        if collection is None:
            raise RuntimeError("Review packet repository cannot update a mapping draft.")
        result = collection.update_one(
            {"_id": str(packet_id)},
            {
                "$set": {
                    "draftMappingId": draft_mapping_id,
                    "draftMappingVersion": draft_mapping_version,
                    "parseStrategy": parse_strategy,
                    "validationGates": validation_gates,
                }
            },
        )
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _file_type(value: object) -> FileType:
        if isinstance(value, FileType):
            return value
        if not isinstance(value, str):
            return FileType.SETTLEMENT
        try:
            return FileType(value)
        except ValueError:
            return FileType.SETTLEMENT
