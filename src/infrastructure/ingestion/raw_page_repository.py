"""Mongo/GridFS adapter for durable raw API page staging."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from shutil import copyfile
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from src.domain.ingestion.raw_pages import RawIngestionPage, RawPageStatus
from src.domain.ingestion.source_units import SourceUnitMetadata
from src.infrastructure.persistence.mongo_repository import BaseRepository


class RawIngestionPageRepository(BaseRepository[RawIngestionPage]):
    """Persist one idempotent raw page and its GridFS payload."""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(collection_name="raw_ingestion_page", db=db)
        self._set_model_class(RawIngestionPage)
        # Instantiate lazily so unit-test/fallback database doubles can use
        # metadata operations without pretending to be a Motor database.
        self._db = db
        self._bucket: AsyncIOMotorGridFSBucket | None = None

    @property
    def bucket(self) -> AsyncIOMotorGridFSBucket:
        if self._bucket is None:
            self._bucket = AsyncIOMotorGridFSBucket(self._db, bucket_name="raw_ingestion")
        return self._bucket

    async def stage_from_path(
        self,
        *,
        stage_key: str,
        partner: str,
        fetch_config_id: str,
        source_type: str,
        stream_key: str,
        reconciliation_date: datetime,
        unit: SourceUnitMetadata,
        retention_days: int = 7,
    ) -> RawIngestionPage:
        """Upload a page once and upsert its metadata.

        A unique source-unit key makes retries safe. Existing staged/consumed
        pages are returned without uploading the payload again.
        """
        existing = await self.find_one({"sourceUnitKey": unit.source_unit_key})
        if existing is not None:
            return existing
        if not unit.local_path:
            raise ValueError("Cannot stage a source unit without localPath")
        path = Path(unit.local_path)
        payload = path.read_bytes()
        file_id = await self.bucket.upload_from_stream(
            path.name,
            BytesIO(payload),
            metadata={
                "stageKey": stage_key,
                "sourceUnitKey": unit.source_unit_key,
                "contentHash": unit.content_hash,
            },
        )
        page = RawIngestionPage(
            stageKey=stage_key,
            partner=partner,
            fetchConfigId=fetch_config_id,
            sourceType=source_type,
            streamKey=stream_key,
            reconciliationDate=reconciliation_date,
            sourceUnitKey=unit.source_unit_key or "",
            page=unit.page,
            cursorBefore=unit.cursor_before,
            cursorAfter=unit.cursor_after,
            contentHash=unit.content_hash,
            contentType=unit.content_type,
            itemCount=unit.item_count or 0,
            hasMore=unit.has_more,
            sampleRows=(unit.fetch_metadata or {}).get("sampleRows", []),
            gridfsFileId=file_id,
            localPath=unit.local_path,
            expiresAt=datetime.now(UTC) + timedelta(days=retention_days),
        )
        try:
            await self.create(page)
        except Exception:
            # If a concurrent retry inserted the same unit, prefer its record.
            existing = await self.find_one({"sourceUnitKey": unit.source_unit_key})
            if existing is not None:
                try:
                    await self.bucket.delete(file_id)
                except Exception:
                    # Preserve the original idempotent result even if cleanup
                    # is temporarily unavailable; retention cleanup can retry.
                    pass
                return existing
            try:
                await self.bucket.delete(file_id)
            except Exception:
                pass
            raise
        return page

    async def find_staged(self, stage_key: str) -> list[RawIngestionPage]:
        return await self.find_many(
            {"stageKey": stage_key, "status": RawPageStatus.STAGED.value}
        )

    async def find_for_replay(self, stage_key: str) -> list[RawIngestionPage]:
        """Return every retained page in deterministic page order."""
        cursor = self.collection.find(
            {
                "stageKey": stage_key,
                "status": {"$in": [RawPageStatus.STAGED.value, RawPageStatus.CONSUMED.value]},
            }
        ).sort([("page", 1), ("createdAt", 1)])
        return [self._from_mongo(raw) async for raw in cursor]

    async def mark_consumed(self, source_unit_key: str) -> bool:
        result = await self.collection.update_one(
            {"sourceUnitKey": source_unit_key, "status": RawPageStatus.STAGED.value},
            {
                "$set": {
                    "status": RawPageStatus.CONSUMED.value,
                    "consumedAt": datetime.now(UTC),
                }
            },
        )
        return result.modified_count == 1

    async def materialize(self, page: RawIngestionPage, destination: str) -> str:
        """Restore a staged page to a local path for the existing reader."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if page.gridfs_file_id is not None:
            with target.open("wb") as output:
                await self.bucket.download_to_stream(page.gridfs_file_id, output)
        elif page.local_path:
            copyfile(page.local_path, target)
        else:
            raise FileNotFoundError(f"Raw payload missing for {page.source_unit_key}")
        return str(target)

    async def cleanup_expired(self, now: datetime | None = None) -> int:
        """Remove expired metadata and its corresponding GridFS objects."""
        now = now or datetime.now(UTC)
        removed = 0
        cursor = self.collection.find(
            {"expiresAt": {"$lte": now}},
            projection={"_id": 1, "gridfsFileId": 1},
        )
        async for document in cursor:
            file_id = document.get("gridfsFileId")
            if file_id is not None:
                await self.bucket.delete(file_id)
            result = await self.collection.delete_one({"_id": document["_id"]})
            removed += int(result.deleted_count or 0)
        return removed
