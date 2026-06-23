import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.api.reconciliation import add_review_note, list_review_records, resolve_review_record


class _AsyncCursor:
    def __init__(self, docs):
        self._docs = docs
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._docs):
            raise StopAsyncIteration
        item = self._docs[self._idx]
        self._idx += 1
        return item


def _make_request(db, actor=None):
    app = FastAPI()
    app.state.db = db
    headers = []
    if actor:
        headers.append((b"x-actor", actor.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "app": app,
        "query_string": b"",
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


class _Collection:
    def __init__(self):
        self.docs = []

    def find(self, query):
        docs = [
            doc for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ]
        return _AsyncCursor(docs)

    async def insert_one(self, document):
        self.docs.append(document)
        class MockResult:
            inserted_id = document.get("_id")
        return MockResult()

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$push" in update:
                    for key, value in update["$push"].items():
                        doc.setdefault(key, []).append(value)
                return
        if upsert:
            doc = dict(query)
            if "$setOnInsert" in update:
                doc.update(update["$setOnInsert"])
            if "$set" in update:
                doc.update(update["$set"])
            if "$push" in update:
                for key, value in update["$push"].items():
                    doc[key] = [value]
            self.docs.append(doc)

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None


class _DB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = _Collection()
        return self.collections[name]


@pytest.mark.asyncio
async def test_list_review_records():
    db = _DB()
    db["reconciliation_review_record"].docs.append(
        {
            "_id": "abc",
            "partner": "MOMO",
            "date": "2026-06-10",
            "recordKey": "txn-1",
            "reviewed": True,
            "resolvedStatus": "MATCHED",
            "notes": [{"time": "2026-06-10 10:00", "event": "note"}],
            "createdAt": "2026-06-10T10:00:00+00:00",
            "updatedAt": "2026-06-10T10:00:00+00:00",
        }
    )
    request = _make_request(db)
    body = await list_review_records(request, partner="MOMO", date="2026-06-10")
    assert len(body["records"]) == 1
    assert body["records"][0]["recordKey"] == "txn-1"


@pytest.mark.asyncio
async def test_add_note_upserts_review_record():
    db = _DB()
    request = _make_request(db, actor="test_user")
    payload = type("Payload", (), {"partner": "MOMO", "date": "2026-06-10", "note": "checked mismatch", "actor": "test_user"})()
    body = await add_review_note(request, "txn-1", payload)
    assert body["ok"] is True
    doc = db["reconciliation_review_record"].docs[0]
    assert doc["recordKey"] == "txn-1"
    assert doc["reviewed"] is True
    assert doc["notes"][0]["event"] == "test_user: checked mismatch"


@pytest.mark.asyncio
async def test_resolve_record_upserts_resolved_status():
    db = _DB()
    request = _make_request(db, actor="test_user")
    payload = type("Payload", (), {"partner": "MOMO", "date": "2026-06-10", "resolved_status": "MATCHED", "actor": "test_user", "note": None})()
    body = await resolve_review_record(request, "txn-1", payload)
    assert body["ok"] is True
    doc = db["reconciliation_review_record"].docs[0]
    assert doc["resolvedStatus"] == "MATCHED"
    assert doc["reviewed"] is True
