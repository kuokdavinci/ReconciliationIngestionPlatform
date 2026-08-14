"""Application queries for selecting the reconciliation execution context."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.config.settings import settings


@dataclass(frozen=True)
class ReconciliationRunContext:
    """The source scope selected for one manual reconciliation run."""

    partner: str
    date: str
    source_file_id: str
    mapping_version: str | None = None


class ReconciliationContextUnavailableError(Exception):
    """No ingested source context is available for the requested run."""


class ReconciliationContextQuery:
    """Resolve the latest ingested source file and mapping scope."""

    def __init__(
        self,
        db,
        *,
        row_counter: Callable[[str], Awaitable[int]],
    ) -> None:
        self.db = db
        self.row_counter = row_counter

    @staticmethod
    def _date_bounds(date_str: str) -> tuple[datetime, datetime]:
        day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        business_timezone = ZoneInfo(settings.business_timezone)
        day = day.astimezone(business_timezone)
        return (
            day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc),
            day.replace(
                hour=23,
                minute=59,
                second=59,
                microsecond=999999,
            ).astimezone(timezone.utc),
        )

    async def latest_context(self, partner: str, date: str) -> dict[str, str]:
        start_of_day, end_of_day = self._date_bounds(date)
        latest_post_approval_run = await self.db["post_approval_run"].find_one(
            {
                "partner": partner,
                "date": date,
                "$or": [
                    {"outputFileId": {"$nin": [None, ""]}},
                    {"sourceFileId": {"$nin": [None, ""]}},
                ],
            },
            sort=[("updatedAt", -1), ("createdAt", -1)],
        )
        latest_scoped_run = await self.db["partner_runtime_run"].find_one(
            {
                "partner": partner,
                "date": date,
                "sourceFileId": {"$nin": [None, ""]},
            },
            sort=[("createdAt", -1)],
        )
        latest_file = await self.db["reconciliation_file"].find_one(
            {
                "partner": partner,
                "reconciliationDate": {"$gte": start_of_day, "$lte": end_of_day},
            },
            sort=[("createdAt", -1)],
        )

        candidates: list[tuple[Any, str, dict[str, Any]]] = []
        if latest_post_approval_run is not None:
            timestamp = latest_post_approval_run.get("updatedAt") or latest_post_approval_run.get(
                "createdAt"
            )
            candidates.append((timestamp, "post_approval_run", latest_post_approval_run))
        if latest_scoped_run is not None:
            timestamp = latest_scoped_run.get("updatedAt") or latest_scoped_run.get("createdAt")
            candidates.append((timestamp, "partner_runtime_run", latest_scoped_run))
        if latest_file is not None:
            candidates.append((latest_file.get("createdAt"), "reconciliation_file", latest_file))
        if not candidates:
            return {}

        candidates.sort(key=lambda item: item[0], reverse=True)
        newest_type = candidates[0][1]
        newest_doc = candidates[0][2]
        context: dict[str, str] = {}
        if newest_type == "post_approval_run":
            output_file_id = newest_doc.get("outputFileId")
            source_file_id = newest_doc.get("sourceFileId")
            if output_file_id:
                context["source_file_id"] = str(output_file_id)
            elif source_file_id:
                context["source_file_id"] = str(source_file_id)
        elif newest_type == "partner_runtime_run":
            if newest_doc.get("sourceFileId"):
                context["source_file_id"] = str(newest_doc["sourceFileId"])
            if newest_doc.get("mappingVersion"):
                context["mapping_version"] = str(newest_doc["mappingVersion"])
        elif newest_type == "reconciliation_file" and newest_doc.get("_id"):
            context["source_file_id"] = str(newest_doc["_id"])
        return context

    async def resolve(self, partner: str, date: str) -> ReconciliationRunContext:
        latest_context = await self.latest_context(partner, date)
        source_file_id = latest_context.get("source_file_id")
        if not source_file_id:
            raise ReconciliationContextUnavailableError(
                "No partner file context is available for this date. Run ingestion first or finish the review flow before reconciling."
            )
        if await self.row_counter(source_file_id) <= 0:
            raise ReconciliationContextUnavailableError(
                "The latest partner file has not been ingested yet. Complete approval/ingestion before running reconciliation."
            )
        return ReconciliationRunContext(
            partner=partner,
            date=date,
            source_file_id=source_file_id,
            mapping_version=latest_context.get("mapping_version"),
        )
