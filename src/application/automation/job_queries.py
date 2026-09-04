"""Application read model for automation job visibility."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from src.application.automation.stream_identity import source_stream_key
from src.application.automation.backfill_service import serialize_backfill_run
from src.application.ingestion.recovery_view import build_recovery_view
from src.application.runtime.service import serialize_partner_runtime_run
from src.application.review.packet_visibility import same_review_source_scope
from src.config.signature import structure_signatures_equivalent
from src.domain.fetch_config.models import FetchMethod
from src.domain.ingestion.checkpoints import IngestionMode
from src.domain.ingestion.retry_policy import RetryPolicy
from src.domain.runtime.models import PartnerRuntimeRunStatus


class AutomationJobQueryService:
    """Build automation job projections from injected repositories."""

    _ACTIVE_RUNTIME_STATUSES = {
        PartnerRuntimeRunStatus.QUEUED.value,
        PartnerRuntimeRunStatus.FETCHING.value,
        PartnerRuntimeRunStatus.INGESTING.value,
        PartnerRuntimeRunStatus.WAITING_REVIEW.value,
        PartnerRuntimeRunStatus.WAITING_RECONCILE.value,
        PartnerRuntimeRunStatus.RECONCILING.value,
    }
    _AIRFLOW_RETRYING_TASK_STATES = {"up_for_retry"}
    _AIRFLOW_MANUAL_RETRY_STATES = {"failed", "upstream_failed", "up_for_retry"}

    def __init__(
        self,
        *,
        db,
        fetch_repo,
        packet_repo,
        runtime_run_repo,
        checkpoint_repo,
        backfill_repo,
        task_state_resolver: Callable[
            [dict[str, Any] | None], Awaitable[str | None]
        ]
        | None = None,
    ) -> None:
        self.db = db
        self.fetch_repo = fetch_repo
        self.packet_repo = packet_repo
        self.runtime_run_repo = runtime_run_repo
        self.checkpoint_repo = checkpoint_repo
        self.backfill_repo = backfill_repo
        self.task_state_resolver = task_state_resolver

    @staticmethod
    def _stream_key_for_config(config) -> str | None:
        try:
            return source_stream_key(config)
        except (AttributeError, ValueError):
            return None

    @staticmethod
    def _merge_runtime_attempt_history(
        recent_runs: list,
        latest_run_data: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for run in reversed(recent_runs):
            for event in getattr(run, "attempt_history", None) or []:
                event_id = str(event.get("eventId") or "") if isinstance(event, dict) else ""
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                merged.append(dict(event))
        for event in (latest_run_data or {}).get("attemptHistory") or []:
            event_id = str(event.get("eventId") or "") if isinstance(event, dict) else ""
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            merged.append(dict(event))
        return merged

    @staticmethod
    def _has_pending_file(
        *,
        fetch_method: FetchMethod,
        latest_file: dict | None,
        latest_run,
        is_duplicate_outcome: bool,
    ) -> bool:
        if fetch_method == FetchMethod.API or latest_file is None or is_duplicate_outcome:
            return False
        if latest_file.get("processingStatus") != "COMPLETED":
            return False
        return (
            latest_run is None
            or latest_run.source_file_id != latest_file["id"]
            or latest_run.status == PartnerRuntimeRunStatus.WAITING_RECONCILE
        )

    @staticmethod
    def _destination(config) -> str:
        method_config = config.get_method_config()
        if method_config is None:
            return "-"
        for attribute in ("remote_path", "base_url", "directory"):
            if hasattr(method_config, attribute):
                return getattr(method_config, attribute)
        return "-"

    async def _task_state(self, latest_run_data: dict[str, Any] | None) -> str | None:
        if self.task_state_resolver is None:
            return None
        value = await self.task_state_resolver(latest_run_data)
        return str(value).lower() if value is not None else None

    async def list_jobs(self) -> list[dict[str, Any]]:
        configs = await self.fetch_repo.find_enabled()
        checkpoint_identities = [
            {
                "partner": config.partner,
                "fetchConfigId": str(config.id),
                "sourceType": config.fetch_method.value,
                "streamKey": self._stream_key_for_config(config),
                "mode": IngestionMode.SCHEDULED,
            }
            for config in configs
        ]
        checkpoints = await self.checkpoint_repo.find_by_streams(checkpoint_identities)
        checkpoint_by_identity = {
            (
                checkpoint.partner,
                checkpoint.fetch_config_id,
                checkpoint.source_type,
                checkpoint.mode,
            ): checkpoint
            for checkpoint in checkpoints
        }
        max_attempts = RetryPolicy().max_attempts
        packets = await self.packet_repo.find_many({})
        packets.sort(key=lambda item: item.created_at, reverse=True)
        pending_by_partner: dict[str, int] = {}
        recent_packet_docs: dict[str, list[dict[str, Any]]] = {}
        pending_packet_keys: set[tuple[str, str, str]] = set()
        approved_packets: dict[tuple[str, str, str], list[Any]] = {}
        for packet in packets:
            if packet.source_type.value != "SCHEDULER_JOB" or packet.status.value != "APPROVED":
                continue
            packet_key = (
                packet.partner,
                packet.source_type.value,
                packet.file_type_detected,
            )
            approved_packets.setdefault(packet_key, []).append(packet)
        for packet in packets:
            if packet.source_type.value != "SCHEDULER_JOB":
                continue
            packet_key = (
                packet.partner,
                packet.source_type.value,
                packet.file_type_detected,
            )
            if (
                packet.status.value == "PENDING"
                and any(
                    structure_signatures_equivalent(
                        packet.structure_signature,
                        approved_packet.structure_signature,
                    )
                    and same_review_source_scope(packet, approved_packet)
                    for approved_packet in approved_packets.get(packet_key, [])
                )
            ):
                # Keep the duplicate packet for audit, but do not expose it
                # as a second review item after a backfill approval.
                continue
            if packet.status.value == "PENDING":
                if packet_key in pending_packet_keys:
                    continue
                pending_packet_keys.add(packet_key)
                pending_by_partner[packet.partner] = pending_by_partner.get(packet.partner, 0) + 1
            recent_packet_docs.setdefault(packet.partner, []).append(
                {
                    "_id": str(packet.id),
                    "fileName": packet.file_name,
                    "status": packet.status.value,
                    "sourceType": packet.source_type.value,
                    "decisionMode": packet.decision_mode.value if packet.decision_mode else None,
                    "recommendedAction": packet.recommended_action,
                    "parseStrategy": packet.parse_strategy,
                    "riskSummary": packet.risk_summary,
                    "createdAt": packet.created_at.isoformat(),
                    "reviewedAt": packet.reviewed_at.isoformat() if packet.reviewed_at else None,
                }
            )
        for partner_packets in recent_packet_docs.values():
            partner_packets.sort(key=lambda item: item["createdAt"], reverse=True)

        jobs: list[dict[str, Any]] = []
        for config in configs:
            latest_run = await self.runtime_run_repo.find_latest_by_partner(config.partner)
            recent_runs = await self.runtime_run_repo.find_recent_by_partner(
                config.partner,
                limit=5,
            )
            latest_file_raw = await self.db["reconciliation_file"].find_one(
                {"partner": config.partner},
                sort=[("createdAt", -1)],
            )
            latest_file = None
            if latest_file_raw is not None:
                latest_file = {
                    "id": str(latest_file_raw.get("_id")),
                    "fileName": latest_file_raw.get("fileName"),
                    "processingStatus": latest_file_raw.get("processingStatus"),
                    "stageSummary": latest_file_raw.get("stageSummary") or {},
                    "reconciliationDate": (
                        latest_file_raw.get("reconciliationDate").isoformat()
                        if isinstance(latest_file_raw.get("reconciliationDate"), datetime)
                        else str(latest_file_raw.get("reconciliationDate") or "")
                    ),
                    "createdAt": (
                        latest_file_raw.get("createdAt").isoformat()
                        if isinstance(latest_file_raw.get("createdAt"), datetime)
                        else str(latest_file_raw.get("createdAt") or "")
                    ),
                    "updatedAt": (
                        latest_file_raw.get("updatedAt").isoformat()
                        if isinstance(latest_file_raw.get("updatedAt"), datetime)
                        else str(latest_file_raw.get("updatedAt") or "")
                    ),
                }

            latest_run_data = serialize_partner_runtime_run(latest_run) if latest_run else None
            attempt_history = self._merge_runtime_attempt_history(recent_runs, latest_run_data)
            airflow_task_state = await self._task_state(latest_run_data)
            if latest_run_data is not None and airflow_task_state is not None:
                latest_run_data.setdefault("orchestration", {})["taskState"] = airflow_task_state
            checkpoint = checkpoint_by_identity.get(
                (
                    config.partner,
                    str(config.id),
                    config.fetch_method.value,
                    IngestionMode.SCHEDULED,
                )
            )
            active_backfill = await self.backfill_repo.find_latest_active_by_partner(config.partner)
            latest_run_stats = (latest_run_data or {}).get("stats") or {}
            duplicate_outcome = latest_run_stats.get("outcome")
            if duplicate_outcome is None and latest_run_stats.get("replayed", 0) > 0:
                duplicate_outcome = "FETCH_UNIT_REPLAY"
            is_safe_duplicate = latest_run_stats.get("safeDuplicate") is True or duplicate_outcome in {
                "FILE_DUPLICATE",
                "FETCH_UNIT_REPLAY",
                "NO_NEW_FILE",
                "SAFE_DUPLICATE",
            }
            airflow_retry_active = airflow_task_state in self._AIRFLOW_RETRYING_TASK_STATES
            airflow_terminal_retry = airflow_task_state in self._AIRFLOW_MANUAL_RETRY_STATES
            application_runtime_active = (
                latest_run_data and latest_run_data.get("status") in self._ACTIVE_RUNTIME_STATUSES
            )
            active_run = (
                latest_run_data
                if latest_run_data
                and (
                    (application_runtime_active and not airflow_terminal_retry)
                    or airflow_retry_active
                )
                else None
            )
            has_pending_file = self._has_pending_file(
                fetch_method=config.fetch_method,
                latest_file=latest_file,
                latest_run=latest_run,
                is_duplicate_outcome=is_safe_duplicate,
            )
            status = "HEALTHY"
            status_message = "No active runtime work."
            if airflow_retry_active:
                status = "RETRYING"
                status_message = "Airflow is retrying this run; wait for it to finish before starting another run."
            elif active_run:
                status = active_run.get("status") or "RUNNING"
                status_message = active_run.get("message") or "Runtime flow is active."
            elif latest_run_data and latest_run_data.get("status") == PartnerRuntimeRunStatus.FAILED.value:
                status = "FAILED"
                status_message = latest_run_data.get("message") or "Latest runtime run failed."
            elif latest_run_data and latest_run_data.get("status") == PartnerRuntimeRunStatus.PARTIAL.value:
                status = "PARTIAL"
                status_message = latest_run_data.get("message") or "Latest runtime run completed with partial records."
            elif airflow_terminal_retry:
                status = "FAILED"
                status_message = "Airflow task failed; Retry will clear the task in the existing DAG run."
            elif is_safe_duplicate:
                status = "SAFE_DUPLICATE"
                status_message = {
                    "FILE_DUPLICATE": "File already processed. Ingestion and reconciliation were skipped safely.",
                    "FETCH_UNIT_REPLAY": "Fetch unit already processed. Ingestion and reconciliation were skipped safely.",
                    "NO_NEW_FILE": "No new file was found. Ingestion and reconciliation were skipped.",
                    "SAFE_DUPLICATE": "This source file was already processed. The retry was skipped safely.",
                }.get(str(duplicate_outcome or ""), "This source file was already processed. The retry was skipped safely.")
            elif has_pending_file:
                status = "PENDING"
                status_message = "A partner file is available and waiting for reconciliation."
            method_config = config.get_method_config()
            expected_unit_count = (
                getattr(method_config.pagination, "max_pages", None)
                if config.fetch_method.value == "API"
                and getattr(method_config, "pagination", None) is not None
                else None
            ) if method_config is not None else None
            jobs.append(
                {
                    "partner": config.partner,
                    "fetchMethod": config.fetch_method.value,
                    "schedule": config.schedule,
                    "enabled": config.enabled,
                    "localDownloadDir": config.local_download_dir,
                    "destination": self._destination(config),
                    "pendingReviewPackets": pending_by_partner.get(config.partner, 0),
                    "updatedAt": config.updated_at.isoformat()
                    if isinstance(config.updated_at, datetime)
                    else str(config.updated_at),
                    "recentPackets": recent_packet_docs.get(config.partner, [])[:3],
                    "status": status,
                    "statusMessage": status_message,
                    "duplicateOutcome": duplicate_outcome,
                    "safeDuplicate": is_safe_duplicate,
                    "duplicateSourceOutcome": latest_run_stats.get("duplicateSourceOutcome"),
                    "duplicateMessage": status_message if is_safe_duplicate else None,
                    "hasPendingFile": has_pending_file,
                    "latestRuntimeRun": latest_run_data,
                    "recentRuntimeRuns": [
                        serialize_partner_runtime_run(item) for item in recent_runs
                    ],
                    "activeRuntimeRun": active_run,
                    "latestFile": latest_file,
                    "recovery": build_recovery_view(
                        checkpoint=checkpoint,
                        latest_run=latest_run_data,
                        max_attempts=max_attempts,
                        attempt_history=attempt_history,
                        expected_unit_count=expected_unit_count,
                    ),
                    "activeBackfill": serialize_backfill_run(active_backfill)
                    if active_backfill
                    else None,
                }
            )
        return jobs
