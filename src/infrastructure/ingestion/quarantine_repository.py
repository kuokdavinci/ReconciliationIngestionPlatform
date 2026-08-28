"""MongoDB adapter for ingestion quarantine records."""

from datetime import UTC, datetime, timedelta
from typing import Any, overload

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from src.domain.ingestion.quarantine import (
    IngestionQuarantineRecord,
    QuarantineAction,
    QuarantinePriority,
    QuarantineQuery,
    QuarantineRetentionPolicy,
    QuarantineResolutionEvent,
    QuarantineStatus,
    assert_quarantine_transition,
    quarantine_error_codes_for_issue_type,
    quarantine_issue_type_for_error_code,
)
from src.config.settings import settings
from src.infrastructure.persistence.mongo_repository import BaseRepository


def _bounded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep lifecycle metadata bounded and free of sensitive evidence."""
    forbidden = ("raw", "fingerprint", "password", "secret", "token", "credential")
    bounded: dict[str, Any] = {}
    for key, value in metadata.items():
        key_text = str(key)
        normalized = "".join(character for character in key_text.lower() if character.isalnum())
        if (
            any(token in normalized for token in forbidden)
            or normalized in {"error", "exception", "trace", "stacktrace", "traceback", "authorization"}
            or (normalized.startswith("error") and normalized != "errorcode")
            or normalized.startswith(("api", "auth"))
        ):
            continue
        if isinstance(value, str):
            bounded[key_text] = value[:512]
        elif isinstance(value, (int, float, bool)) or value is None:
            bounded[key_text] = value
    return bounded


def _bounded_text(value: str, *, max_length: int = 500) -> str:
    text = value.strip()
    return text[:max_length] if text else ""


@overload
def _bounded_action_id(action_id: str) -> str: ...


@overload
def _bounded_action_id(action_id: None) -> None: ...


def _bounded_action_id(action_id: str | None) -> str | None:
    if action_id is None:
        return None
    text = action_id.strip()
    if not 1 <= len(text) <= 128:
        raise ValueError("action_id must be 1 to 128 characters")
    return text


def _bounded_limit(value: int, *, maximum: int = 200) -> int:
    return max(1, min(int(value), maximum))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _claim_expired(record: IngestionQuarantineRecord, now: datetime) -> bool:
    """Treat newly written expired leases as immutable by their old owner."""
    expiration = record.claim_expires_at
    return isinstance(expiration, datetime) and _as_utc(expiration) <= now


class IngestionQuarantineRepository(BaseRepository[IngestionQuarantineRecord]):
    """Store rejected rows independently from canonical transactions."""

    def __init__(
        self,
        db: AsyncIOMotorDatabase,
        retention_policy: QuarantineRetentionPolicy | None = None,
    ):
        super().__init__(collection_name="ingestion_quarantine_record", db=db)
        self._set_model_class(IngestionQuarantineRecord)
        self.retention_policy = retention_policy or QuarantineRetentionPolicy()

    async def create_many(self, records: list[IngestionQuarantineRecord]) -> int:
        if not records:
            return 0
        expires_at = datetime.now(UTC) + timedelta(
            days=settings.ingestion_quarantine_retention_days
        )
        documents = [
            self._to_mongo(
                record.model_copy(update={"expires_at": expires_at})
                if record.expires_at is None
                else record.model_copy(
                    update={
                        "expires_at": min(
                            _as_utc(record.expires_at),
                            expires_at,
                        )
                    }
                )
            )
            for record in records
        ]
        await self.collection.insert_many(documents)
        return len(records)

    async def rebind_source_file(self, source_file_id: str, target_source_file_id: str) -> int:
        """Move quarantine lineage to the logical file kept for a staged stream."""
        result = await self.collection.update_many(
            {"sourceFileId": source_file_id},
            {"$set": {"sourceFileId": target_source_file_id}},
        )
        return int(getattr(result, "modified_count", 0) or 0)

    async def find_by_id(self, record_id: str) -> IngestionQuarantineRecord | None:
        return await self.find_one({"_id": record_id})

    @staticmethod
    def _event_payload(event: QuarantineResolutionEvent) -> dict[str, Any]:
        return BaseRepository._convert_special_types(
            event.model_dump(by_alias=True)
        )

    @staticmethod
    def _query_filters(query: QuarantineQuery, *, now: datetime | None = None) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        if query.partner is not None:
            filters["partner"] = query.partner
        if query.status is not None:
            filters["status"] = query.status.value
        if query.phase is not None:
            filters["phase"] = query.phase.value
        if query.error_code is not None:
            filters["errors.errorCode"] = query.error_code
        if query.source_file_id is not None:
            filters["sourceFileId"] = query.source_file_id
        if query.source_unit_key is not None:
            filters["sourceUnitKey"] = query.source_unit_key
        if query.review_packet_id is not None:
            filters["reviewPacketId"] = query.review_packet_id
        if query.post_approval_run_id is not None:
            filters["postApprovalRunId"] = query.post_approval_run_id
        if query.claimed_by is not None:
            filters["claimedBy"] = query.claimed_by
        if query.priority is not None:
            filters["priority"] = query.priority.value
        if query.issue_type is not None:
            filters["errors.errorCode"] = {
                "$in": list(quarantine_error_codes_for_issue_type(query.issue_type))
            }
        if query.overdue is not None:
            now = now or datetime.now(UTC)
            if query.overdue:
                if query.status is None:
                    filters["status"] = {
                        "$in": [
                            QuarantineStatus.PENDING.value,
                            QuarantineStatus.REPROCESSING.value,
                        ]
                    }
                filters["reviewDueAt"] = {"$lte": now}
            else:
                filters["reviewDueAt"] = {"$gt": now}
        if query.from_date is not None or query.to_date is not None:
            date_filter: dict[str, datetime] = {}
            if query.from_date is not None:
                date_filter["$gte"] = query.from_date
            if query.to_date is not None:
                date_filter["$lt"] = query.to_date
            filters["createdAt"] = date_filter
        if query.cursor is not None:
            cursor_date_text, cursor_id = query.cursor.split("|", maxsplit=1)
            cursor_date = datetime.fromisoformat(cursor_date_text)
            filters["$or"] = [
                {"createdAt": {"$gt": cursor_date}},
                {"createdAt": cursor_date, "_id": {"$gt": cursor_id}},
            ]
        return filters

    async def claim(
        self,
        record_id: str,
        operator_id: str,
        lease_seconds: int = 900,
        *,
        action_id: str | None = None,
    ) -> IngestionQuarantineRecord | None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")
        action_id = _bounded_action_id(action_id)
        current = await self.find_by_id(record_id)
        if current is None or current.status is not QuarantineStatus.PENDING:
            return None

        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=lease_seconds)
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.PENDING,
            toStatus=QuarantineStatus.REPROCESSING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason="Quarantine record claimed for processing.",
            attempt=current.attempt_count + 1,
            actionId=action_id,
            outcome="CLAIMED",
            metadata={
                "leaseSeconds": lease_seconds,
                "claimedBy": operator_id,
                "priority": current.priority.value,
                "reviewDueAt": (
                    current.review_due_at.isoformat()
                    if current.review_due_at is not None
                    else None
                ),
            },
        )
        filters: dict[str, Any] = {
            "_id": record_id,
            "status": QuarantineStatus.PENDING.value,
        }
        if action_id is not None:
            filters["resolutionHistory.actionId"] = {"$ne": action_id}
        raw = await self.collection.find_one_and_update(
            filters,
            {
                "$set": {
                    "status": QuarantineStatus.REPROCESSING.value,
                    "claimedBy": operator_id,
                    "claimedAt": now,
                    "claimExpiresAt": claim_expires_at,
                    "lastAttemptError": None,
                    "lastActionId": action_id,
                    "updatedAt": now,
                },
                "$inc": {"attemptCount": 1},
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            return None
        return self._from_mongo(raw)

    async def reclaim_expired_claim(
        self,
        record_id: str,
    ) -> IngestionQuarantineRecord | None:
        """Return an expired processing claim to the pending queue atomically."""
        now = datetime.now(UTC)
        raw = await self.collection.find_one_and_update(
            {
                "_id": record_id,
                "status": QuarantineStatus.REPROCESSING.value,
                "claimExpiresAt": {"$lte": now},
            },
            {
                "$set": {
                    "status": QuarantineStatus.PENDING.value,
                    "claimedBy": None,
                    "claimedAt": None,
                    "claimExpiresAt": None,
                    "lastAttemptError": "Operator claim lease expired.",
                    "updatedAt": now,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        return self._from_mongo(raw) if raw is not None else None

    async def reserve_action(
        self,
        record_id: str,
        operator_id: str,
        action_id: str,
        action: QuarantineAction,
    ) -> str:
        """Reserve one resolution action before external persistence work."""
        action_id = _bounded_action_id(action_id)
        if action_id is None:
            raise ValueError("action_id is required")
        raw = await self.collection.find_one_and_update(
            {
                "_id": record_id,
                "status": QuarantineStatus.REPROCESSING.value,
                "claimedBy": operator_id,
                "resolutionHistory.actionId": {"$ne": action_id},
                "$or": [
                    {"activeActionId": {"$exists": False}},
                    {"activeActionId": None},
                ],
            },
            {
                "$set": {
                    "activeActionId": action_id,
                    "activeActionActor": operator_id,
                    "activeAction": action.value,
                    "activeActionStartedAt": datetime.now(UTC),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if raw is not None:
            return "RESERVED"

        current = await self.collection.find_one(
            {"_id": record_id},
            projection={"activeActionId": 1, "resolutionHistory": 1},
        )
        if current is None:
            return "NOT_FOUND"
        if any(
            event.get("actionId") == action_id
            for event in current.get("resolutionHistory", [])
            if isinstance(event, dict)
        ):
            return "COMPLETED"
        return "IN_PROGRESS" if current.get("activeActionId") else "CONFLICT"

    async def find_pending(self, *, partner: str | None = None, limit: int = 100) -> list[IngestionQuarantineRecord]:
        query: dict[str, Any] = {"status": QuarantineStatus.PENDING.value}
        if partner is not None:
            query["partner"] = partner
        cursor = self.collection.find(query).sort("createdAt", 1).limit(_bounded_limit(limit))
        records = []
        async for raw in cursor:
            records.append(self._from_mongo(raw))
        return records

    async def find_blockers(self, source_unit_key: str) -> list[IngestionQuarantineRecord]:
        """Return active quarantine records associated with one source unit."""
        cursor = self.collection.find(
            {
                "sourceUnitKey": source_unit_key,
                "status": {
                    "$in": [
                        QuarantineStatus.PENDING.value,
                        QuarantineStatus.REPROCESSING.value,
                    ]
                },
            }
        ).sort([("createdAt", 1), ("_id", 1)])
        return [self._from_mongo(raw) async for raw in cursor]

    async def has_unresolved_blockers(self, source_unit_key: str) -> bool:
        """Check only active conflicting duplicates for a source-unit hold."""
        raw = await self.collection.find_one(
            {
                "sourceUnitKey": source_unit_key,
                "status": {
                    "$in": [
                        QuarantineStatus.PENDING.value,
                        QuarantineStatus.REPROCESSING.value,
                    ]
                },
                "errors.errorCode": "CONFLICTING_DUPLICATE",
            },
            projection={"_id": 1},
        )
        return raw is not None

    async def purge_expired(self, now: datetime | None = None, limit: int = 100) -> int:
        """Delete only bounded, expired terminal evidence records."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        now = now or datetime.now(UTC)
        cursor = self.collection.find(
            {
                "status": {
                    "$in": [
                        QuarantineStatus.RESOLVED.value,
                        QuarantineStatus.REJECTED.value,
                    ]
                },
                "retentionUntil": {"$lte": now},
            },
            projection={"_id": 1},
        ).sort([("retentionUntil", 1), ("_id", 1)]).limit(limit)
        removed = 0
        async for raw in cursor:
            result = await self.collection.delete_one({"_id": raw["_id"]})
            removed += int(result.deleted_count or 0)
        return removed

    @overload
    async def find_many(
        self,
        query: dict[Any, Any],
    ) -> list[IngestionQuarantineRecord]: ...

    @overload
    async def find_many(
        self,
        query: QuarantineQuery,
        *,
        now: datetime | None = None,
    ) -> tuple[list[IngestionQuarantineRecord], str | None]: ...

    async def find_many(
        self,
        query: dict[Any, Any] | QuarantineQuery,
        *,
        now: datetime | None = None,
    ) -> list[IngestionQuarantineRecord] | tuple[list[IngestionQuarantineRecord], str | None]:
        if isinstance(query, dict):
            return await super().find_many(query)
        filters = self._query_filters(query, now=now)

        cursor = self.collection.find(filters).sort(
            [("createdAt", 1), ("_id", 1)]
        ).limit(query.limit + 1)
        records = [self._from_mongo(raw) async for raw in cursor]
        next_cursor = None
        has_next_page = len(records) > query.limit
        records = records[:query.limit]
        if has_next_page and records:
            last = records[-1]
            next_cursor = f"{last.created_at.isoformat()}|{last.id}"
        return records, next_cursor

    async def release_for_retry(
        self,
        record_id: str,
        operator_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
        action_id: str | None = None,
        outcome: str | None = None,
    ) -> bool:
        action_id = _bounded_action_id(action_id)
        reason = _bounded_text(reason)
        current = await self.find_by_id(record_id)
        now = datetime.now(UTC)
        if (
            current is None
            or current.status is not QuarantineStatus.REPROCESSING
            or current.claimed_by != operator_id
            or _claim_expired(current, now)
        ):
            return False
        assert_quarantine_transition(
            QuarantineStatus.REPROCESSING,
            QuarantineStatus.PENDING,
        )
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=QuarantineStatus.PENDING,
            action=QuarantineAction.REPROCESS,
            actor=operator_id,
            reason=reason,
            attempt=current.attempt_count,
            actionId=action_id,
            outcome=outcome,
            metadata=_bounded_metadata(metadata or {}),
        )
        filters: dict[str, Any] = {
            "_id": record_id,
            "status": QuarantineStatus.REPROCESSING.value,
            "claimedBy": operator_id,
        }
        if action_id is not None:
            filters["resolutionHistory.actionId"] = {"$ne": action_id}
        if current.claim_expires_at is not None:
            filters["claimExpiresAt"] = {"$gt": now}
        result = await self.collection.update_one(
            filters,
            {
                "$set": {
                    "status": QuarantineStatus.PENDING.value,
                    "claimedBy": None,
                    "claimedAt": None,
                    "claimExpiresAt": None,
                    "lastAttemptError": reason,
                    "lastActionId": action_id,
                    "updatedAt": now,
                },
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
                "$unset": {
                    "activeActionId": "",
                    "activeActionActor": "",
                    "activeAction": "",
                    "activeActionStartedAt": "",
                },
            },
        )
        return result.modified_count == 1

    async def resolve(
        self,
        record_id: str,
        target: QuarantineStatus,
        operator_id: str,
        action: QuarantineAction,
        reason: str,
        metadata: dict[str, Any] | None = None,
        action_id: str | None = None,
        outcome: str | None = None,
    ) -> bool:
        assert_quarantine_transition(QuarantineStatus.REPROCESSING, target)
        action_id = _bounded_action_id(action_id)
        current = await self.find_by_id(record_id)
        now = datetime.now(UTC)
        if (
            current is None
            or current.status is not QuarantineStatus.REPROCESSING
            or current.claimed_by != operator_id
            or _claim_expired(current, now)
        ):
            return False
        retention_until = now + timedelta(days=self.retention_policy.days_for(target))
        event = QuarantineResolutionEvent(
            fromStatus=QuarantineStatus.REPROCESSING,
            toStatus=target,
            action=action,
            actor=operator_id,
            reason=_bounded_text(reason),
            attempt=current.attempt_count,
            actionId=action_id,
            outcome=outcome,
            metadata=_bounded_metadata(metadata or {}),
        )
        bounded_metadata = _bounded_metadata(metadata or {})
        filters: dict[str, Any] = {
            "_id": record_id,
            "status": QuarantineStatus.REPROCESSING.value,
            "claimedBy": operator_id,
        }
        if action_id is not None:
            filters["resolutionHistory.actionId"] = {"$ne": action_id}
        if current.claim_expires_at is not None:
            filters["claimExpiresAt"] = {"$gt": now}
        result = await self.collection.update_one(
            filters,
            {
                "$set": {
                    "status": target.value,
                    "claimedBy": None,
                    "claimedAt": None,
                    "claimExpiresAt": None,
                    "lastAttemptError": None,
                    "resolutionMetadata": bounded_metadata,
                    "retentionUntil": retention_until,
                    "lastActionId": action_id,
                    "updatedAt": now,
                },
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
                "$unset": {
                    "activeActionId": "",
                    "activeActionActor": "",
                    "activeAction": "",
                    "activeActionStartedAt": "",
                },
            },
        )
        return result.modified_count == 1

    async def find_action(
        self,
        record_id: str,
        action_id: str,
    ) -> QuarantineResolutionEvent | None:
        action_id = _bounded_action_id(action_id)
        raw = await self.collection.find_one(
            {"_id": record_id, "resolutionHistory.actionId": action_id}
        )
        if raw is None:
            return None
        record = self._from_mongo(raw)
        return next(
            (
                event
                for event in record.resolution_history
                if event.action_id == action_id
            ),
            None,
        )

    async def summarize(
        self,
        query: QuarantineQuery,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        base = self._query_filters(query, now=now)

        async def count(extra: dict[str, Any] | None = None) -> int:
            if not extra:
                filters = base
            elif not base:
                filters = extra
            else:
                filters = {"$and": [base, extra]}
            return int(await self.collection.count_documents(filters))

        async def status_count(status: QuarantineStatus) -> int:
            if query.status is not None and query.status is not status:
                return 0
            return await count({"status": status.value})

        now = now or datetime.now(UTC)
        overdue_filter = {
            "status": {
                "$in": [
                    QuarantineStatus.PENDING.value,
                    QuarantineStatus.REPROCESSING.value,
                ]
            },
            "reviewDueAt": {"$lte": now},
        }
        return {
            "total": await count(),
            "pending": await status_count(QuarantineStatus.PENDING),
            "reprocessing": await status_count(QuarantineStatus.REPROCESSING),
            "resolved": await status_count(QuarantineStatus.RESOLVED),
            "rejected": await status_count(QuarantineStatus.REJECTED),
            "overdue": 0
            if query.status in {QuarantineStatus.RESOLVED, QuarantineStatus.REJECTED}
            else await count(overdue_filter),
            "highPriority": await count({"priority": QuarantinePriority.HIGH.value}),
        }

    async def group_summaries(
        self,
        query: QuarantineQuery,
        *,
        now: datetime | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Return bounded packet/run groups for the operator queue.

        The quarantine document remains the source of truth.  Grouping is a
        read projection, capped so a malformed or very large batch cannot
        turn the queue endpoint into an unbounded export.
        """
        now = now or datetime.now(UTC)
        filters = self._query_filters(query.model_copy(update={"limit": 200, "cursor": None}), now=now)
        cursor = self.collection.find(filters).sort([("createdAt", 1), ("_id", 1)]).limit(
            _bounded_limit(limit, maximum=2000)
        )
        groups: dict[str, dict[str, Any]] = {}
        async for raw in cursor:
            record = self._from_mongo(raw)
            key = (
                record.post_approval_run_id
                or record.review_packet_id
                or record.source_file_id
            )
            group = groups.setdefault(
                key,
                {
                    "groupKey": key,
                    "reviewPacketId": record.review_packet_id,
                    "postApprovalRunId": record.post_approval_run_id,
                    "sourceFileId": record.source_file_id,
                    "partner": record.partner,
                    "total": 0,
                    "pending": 0,
                    "reprocessing": 0,
                    "resolved": 0,
                    "rejected": 0,
                    "overdue": 0,
                    "highPriority": 0,
                    "issueTypes": set(),
                },
            )
            group["total"] += 1
            group[record.status.value.lower()] += 1
            if (
                record.status in {QuarantineStatus.PENDING, QuarantineStatus.REPROCESSING}
                and record.review_due_at is not None
                and _as_utc(record.review_due_at) <= now
            ):
                group["overdue"] += 1
            if record.priority is QuarantinePriority.HIGH:
                group["highPriority"] += 1
            for error in record.errors:
                code = error.get("errorCode") if isinstance(error, dict) else None
                if code:
                    group["issueTypes"].add(
                        quarantine_issue_type_for_error_code(str(code)).value
                    )
        return [
            {**group, "issueTypes": sorted(group["issueTypes"])}
            for group in groups.values()
        ]

    async def escalate(
        self,
        record_id: str,
        operator_id: str,
        action_id: str,
        expected_status: QuarantineStatus,
        reason: str,
    ) -> IngestionQuarantineRecord | None:
        action_id = _bounded_action_id(action_id)
        current = await self.find_by_id(record_id)
        if current is None:
            return None
        if current.status not in {
            QuarantineStatus.PENDING,
            QuarantineStatus.REPROCESSING,
        }:
            return None
        if current.status is not expected_status:
            return None
        if current.status is QuarantineStatus.REPROCESSING and current.claimed_by != operator_id:
            return None
        if current.escalation_level >= 3:
            return None

        now = datetime.now(UTC)
        if current.status is QuarantineStatus.REPROCESSING and _claim_expired(current, now):
            return None
        target_level = min(current.escalation_level + 1, 3)
        bounded_reason = _bounded_text(reason)
        event = QuarantineResolutionEvent(
            fromStatus=current.status,
            toStatus=current.status,
            action=QuarantineAction.ESCALATE,
            actor=operator_id,
            reason=bounded_reason,
            attempt=current.attempt_count,
            actionId=action_id,
            outcome="ESCALATED",
            metadata={
                "escalationLevel": target_level,
                "claimedBy": operator_id if current.status is QuarantineStatus.REPROCESSING else None,
                "priority": current.priority.value,
                "reviewDueAt": (
                    current.review_due_at.isoformat()
                    if current.review_due_at is not None
                    else None
                ),
            },
        )
        filters: dict[str, Any] = {
            "_id": record_id,
            "status": current.status.value,
            "escalationLevel": current.escalation_level,
        }
        if current.status is QuarantineStatus.REPROCESSING:
            filters["claimedBy"] = operator_id
        if action_id is not None:
            filters["resolutionHistory.actionId"] = {"$ne": action_id}
        if current.claim_expires_at is not None:
            filters["claimExpiresAt"] = {"$gt": now}
        result = await self.collection.update_one(
            filters,
            {
                "$set": {
                    "escalationLevel": target_level,
                    "escalatedAt": now,
                    "escalatedBy": operator_id,
                    "lastActionId": action_id,
                    "updatedAt": now,
                },
                "$push": {
                    "resolutionHistory": self._event_payload(event),
                },
            },
        )
        if result.modified_count != 1:
            return None
        return await self.find_by_id(record_id)
