"""Rule-based Copilot context for the operations dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Optional

from fastapi import HTTPException

from src.models.mapping_config import MappingConfigRepository, MappingConfigStatus
from src.models.reconciliation_file import ReconciliationFileRepository
from src.models.review_packet import ReviewPacketRepository, ReviewPacketStatus


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else ""


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _date_range(date: str) -> dict[str, datetime]:
    try:
        parsed = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")
    return {
        "$gte": datetime.combine(parsed, time.min, tzinfo=timezone.utc),
        "$lte": datetime.combine(parsed, time.max, tzinfo=timezone.utc),
    }


def _latest(items: list[Any], *attrs: str) -> Any | None:
    if not items:
        return None

    def key(item: Any) -> datetime:
        for attr in attrs:
            value = getattr(item, attr, None)
            if value:
                return _coerce_datetime(value)
        return datetime.min.replace(tzinfo=timezone.utc)

    return max(items, key=key)


def _safe_check(label: str, passed: bool, warn: bool = False) -> dict[str, str]:
    status = "pass" if passed else "warn" if warn else "fail"
    return {"label": label, "status": status}


def _business_copy(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value
    text = text.replace("proposal is ready for review", "a review item is ready")
    text = text.replace("Proposal is ready for review", "A review item is ready")
    text = text.replace("mapping proposal", "draft mapping")
    text = text.replace("Mapping proposal", "Draft mapping")
    text = text.replace("review packet", "review item")
    text = text.replace("Review packet", "Review item")
    return text


@dataclass
class CopilotResolution:
    context: dict[str, Any]
    refs: dict[str, Optional[str]]


class CopilotContextService:
    """Builds a dashboard-facing Copilot recommendation without exposing raw queues."""

    def __init__(self, db):
        self.mapping_repo = MappingConfigRepository(db)
        self.file_repo = ReconciliationFileRepository(db)
        self.packet_repo = ReviewPacketRepository(db)

    async def resolve(
        self,
        *,
        partner: str,
        date: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> CopilotResolution:
        if not partner or not partner.strip():
            raise HTTPException(status_code=400, detail="Partner is required.")
        partner = partner.strip()

        file_query: dict[str, Any] = {"partner": partner}
        if file_id:
            file_query["_id"] = file_id
        elif date:
            file_query["reconciliationDate"] = _date_range(date)

        files = await self.file_repo.find_many(file_query)
        if file_id and not files:
            raise HTTPException(status_code=404, detail="File context not found.")

        mappings = await self.mapping_repo.find_many({"partner": partner})
        packets = await self.packet_repo.find_many({"partner": partner})

        approved_runtime = _latest(
            [item for item in mappings if _enum_value(item.status) == MappingConfigStatus.APPROVED.value],
            "approved_at",
            "created_at",
        )
        pending_proposals = [
            item for item in mappings if _enum_value(item.status) == MappingConfigStatus.PENDING_APPROVAL.value
        ]
        pending_packet = _latest(
            [item for item in packets if _enum_value(item.status) == ReviewPacketStatus.PENDING.value],
            "created_at",
        )
        pending_proposal = _latest(pending_proposals, "created_at")
        latest_file = _latest(files, "uploaded_at", "created_at", "reconciliation_date")

        has_runtime = approved_runtime is not None
        has_packet = pending_packet is not None
        has_draft = pending_proposal is not None
        has_usable_draft = has_packet or has_draft

        latest_file_status = _enum_value(getattr(latest_file, "processing_status", None)) if latest_file else ""
        latest_file_has_warnings = bool(
            latest_file
            and (
                latest_file_status in {"FAILED", "PROCESSING"}
                or int(getattr(latest_file, "failed_rows", 0) or 0) > 0
            )
        )

        if not has_runtime and not has_usable_draft:
            status = "blocked"
        elif has_packet or has_draft:
            status = "needs_review"
        elif latest_file_has_warnings:
            status = "monitor"
        else:
            status = "healthy"

        risk_level = self._risk_level(status, has_runtime, latest_file_status)
        headline = self._headline(partner, status, has_runtime, has_packet, has_draft, latest_file_status)
        explanation = self._explanation(
            status=status,
            has_runtime=has_runtime,
            has_packet=has_packet,
            has_draft=has_draft,
            latest_file=latest_file,
            latest_file_status=latest_file_status,
        )
        primary_action, secondary_actions, decision_actions = self._actions(
            status=status,
            has_packet=has_packet,
            has_draft=has_draft,
            has_runtime=has_runtime,
        )

        # Backward-compatible flat actions list (primary + all secondary)
        full_actions: list[dict[str, Any]] = []
        if primary_action is not None:
            full_actions.append(primary_action)
        full_actions.extend(secondary_actions)

        # step field for 3-step brief flow
        if status == "healthy" or status == "monitor":
            step = "brief"
        elif has_packet or has_draft:
            step = "decision" if decision_actions else "review"
        else:
            step = "brief"

        context = {
            "step": step,
            "status": status,
            "riskLevel": risk_level,
            "headline": headline,
            "explanation": explanation,
            "recommendedAction": primary_action,
            "actions": full_actions,
            "primaryAction": primary_action,
            "secondaryActions": secondary_actions,
            "decisionActions": decision_actions,
            "summary": self._summary(status=status, has_runtime=has_runtime, has_packet=has_packet, has_draft=has_draft),
            "reasons": self._reasons(
                status=status,
                has_runtime=has_runtime,
                has_packet=has_packet,
                has_draft=has_draft,
                latest_file=latest_file,
                latest_file_status=latest_file_status,
            ),
            "evidence": {
                "latestFile": self._file_evidence(latest_file),
                "runtime": {
                    "state": "approved" if has_runtime else "missing",
                    "version": getattr(approved_runtime, "config_version", None) if approved_runtime else None,
                },
                "proposal": self._proposal_evidence(pending_packet, pending_proposal),
                "safeChecks": [
                    _safe_check("Approved runtime exists", has_runtime),
                    _safe_check("Draft ready", has_usable_draft, warn=has_runtime),
                    _safe_check("Latest file can continue", not latest_file_has_warnings, warn=has_runtime),
                ],
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        refs = {
            "reviewItemId": str(pending_packet.id) if pending_packet else None,
            "draftMappingId": str(pending_proposal.id) if pending_proposal else None,
            "latestFileId": str(latest_file.id) if latest_file else None,
        }
        return CopilotResolution(context=context, refs=refs)

    async def context(
        self,
        *,
        partner: str,
        date: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return (await self.resolve(partner=partner, date=date, file_id=file_id)).context

    def _risk_level(self, status: str, has_runtime: bool, latest_file_status: str) -> str:
        if status == "blocked" or (status == "needs_review" and not has_runtime):
            return "high"
        if status == "needs_review" or latest_file_status == "FAILED":
            return "medium"
        if status == "monitor":
            return "medium"
        return "low"

    def _headline(
        self,
        partner: str,
        status: str,
        has_runtime: bool,
        has_packet: bool,
        has_draft: bool,
        latest_file_status: str,
    ) -> str:
        if status == "blocked":
            return f"{partner} is blocked until a runtime mapping is approved"
        if status == "needs_review":
            if not has_runtime:
                return f"{partner} cannot continue safely until a draft is reviewed"
            if has_packet:
                return "File structure changed; a review item is ready"
            if has_draft:
                return "A draft mapping is waiting for review"
        if status == "monitor":
            if latest_file_status == "FAILED":
                return "Latest file needs monitoring, but approved runtime remains available"
            return "Runtime is available; monitor the latest file outcome"
        return "No action needed"

    def _summary(
        self,
        *,
        status: str,
        has_runtime: bool,
        has_packet: bool,
        has_draft: bool,
    ) -> str:
        if status == "blocked":
            return _business_copy("No approved runtime is available.")
        if status == "needs_review":
            return _business_copy("A review item is waiting before runtime changes can be approved.")
        if status == "monitor":
            return _business_copy("Latest file needs monitoring, but approved runtime remains available.")
        return _business_copy("Runtime is ready and no action is required.")

    def _reasons(
        self,
        *,
        status: str,
        has_runtime: bool,
        has_packet: bool,
        has_draft: bool,
        latest_file: Any | None,
        latest_file_status: str,
    ) -> list[str]:
        reasons: list[str] = []
        reasons.append(
            _business_copy(
                "An approved runtime config is active." if has_runtime else "No approved runtime config is active."
            )
        )
        if has_packet:
            reasons.append(_business_copy("A review item is waiting for a reviewer decision."))
        elif has_draft:
            reasons.append(_business_copy("A draft mapping is waiting for review."))
        elif status == "blocked":
            reasons.append(_business_copy("No usable draft is available yet."))
        else:
            reasons.append(_business_copy("No mapping review action is waiting."))
        if latest_file is not None:
            if latest_file_status == "FAILED":
                reasons.append(_business_copy("The latest file failed processing."))
            elif int(getattr(latest_file, "failed_rows", 0) or 0) > 0:
                reasons.append(_business_copy("The latest file has row-level failures."))
            else:
                reasons.append(_business_copy("The latest file has no blocking processing failure."))
        return reasons[:3]

    def _explanation(
        self,
        *,
        status: str,
        has_runtime: bool,
        has_packet: bool,
        has_draft: bool,
        latest_file: Any | None,
        latest_file_status: str,
    ) -> list[str]:
        lines: list[str] = []
        if has_runtime:
            lines.append(_business_copy("An approved runtime config is active."))
        else:
            lines.append(_business_copy("No approved runtime config is active."))

        if has_packet:
            lines.append(_business_copy("A review item is waiting for a reviewer decision."))
        elif has_draft:
            lines.append(_business_copy("A draft mapping is waiting for review."))
        elif status == "blocked":
            lines.append(_business_copy("No usable draft is available yet."))
        else:
            lines.append(_business_copy("No mapping review action is waiting."))

        if latest_file is None:
            lines.append(_business_copy("No file has been received for this context."))
        elif latest_file_status == "FAILED":
            lines.append(_business_copy("The latest file failed processing."))
        elif int(getattr(latest_file, "failed_rows", 0) or 0) > 0:
            lines.append(_business_copy("The latest file has row-level failures."))
        else:
            lines.append(_business_copy("The latest file has no blocking processing failure."))
        return lines

    def _actions(
        self,
        *,
        status: str,
        has_packet: bool,
        has_draft: bool,
        has_runtime: bool,
    ) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        secondary: list[dict[str, Any]] = [
            {
                "key": "refresh_context",
                "label": "Refresh recommendation",
                "style": "secondary",
                "enabled": True,
            }
        ]
        primary: Optional[dict[str, Any]] = None
        decision: list[dict[str, Any]] = []

        if status == "healthy":
            return None, secondary, decision

        if has_packet or has_draft:
            primary = {
                "key": "review_proposal",
                "label": "Open Review Center",
                "style": "primary",
                "enabled": True,
            }
            secondary.append({
                "key": "open_mapping_details",
                "label": "Open mapping details",
                "style": "secondary",
                "enabled": True,
            })
            if has_packet:
                decision = [
                    {
                        "key": "approve_activate_next_runtime",
                        "label": "Approve activate next runtime",
                        "style": "secondary",
                        "enabled": True,
                    },
                    {
                        "key": "approve_keep_current",
                        "label": "Keep current",
                        "style": "secondary",
                        "enabled": has_runtime,
                    },
                    {
                        "key": "reject_proposal",
                        "label": "Reject",
                        "style": "secondary",
                        "enabled": True,
                    },
                ]
            return primary, secondary, decision

        # monitor or blocked (no pending review, but no runtime or file warnings)
        label = "Open Mapping Studio" if status == "blocked" else "Open mapping details or Open file details"
        primary = {
            "key": "open_mapping_details",
            "label": label,
            "style": "primary",
            "enabled": True,
        }
        return primary, secondary, decision

    def _file_evidence(self, latest_file: Any | None) -> Optional[dict[str, Any]]:
        if latest_file is None:
            return None
        return {
            "name": latest_file.file_name,
            "status": _enum_value(latest_file.processing_status).lower(),
            "totalRows": latest_file.total_rows,
            "successRows": latest_file.success_rows,
            "failedRows": latest_file.failed_rows,
        }

    def _proposal_evidence(self, pending_packet: Any | None, pending_proposal: Any | None) -> dict[str, Any]:
        if pending_packet is not None:
            return {
                "state": "pending_review",
                "source": "review_packet",
                "reason": _business_copy(
                    pending_packet.risk_summary.get("summary")
                    or pending_packet.recommended_action.get("reason")
                ),
            }
        if pending_proposal is not None:
            return {
                "state": "pending_review",
                "source": "mapping_proposal",
                "reason": _business_copy((pending_proposal.config_health or {}).get("reasoning")),
            }
        return {"state": "none"}
