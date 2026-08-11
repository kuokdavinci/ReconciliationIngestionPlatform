import json
from datetime import UTC, datetime

import pytest

from scripts.demo.sprint2.evaluation import run_sprint2_evaluation
from scripts.demo.sprint2.fixture import (
    MockAPIError,
    ViettelPayMockFixture,
    reset_viettelpay_fixture,
)
from scripts.demo.sprint2.seed import _mapping_document, _wipe_mongo
from src.config.validator import ConfigValidator
from src.domain.mapping.models import MappingConfig
from src.normalizer.normalizer import TransactionNormalizer
from src.validators.validator import Validator


def test_viettelpay_fixture_exposes_three_cursor_pages_and_controlled_failure():
    fixture = ViettelPayMockFixture(fail_once_page=2)

    first = fixture.fetch_page(page=1, cursor=None)
    assert first["page"] == 1
    assert first["cursorAfter"] == "cursor-1"
    assert first["items"]
    assert set(first["items"][0]) == {
        "id",
        "trace",
        "amount",
        "currency",
        "status",
        "transDate",
    }
    assert first["items"][0]["trace"] == first["items"][0]["id"]
    assert first["items"][0]["currency"] == "VND"
    assert first["items"][0]["transDate"]

    with pytest.raises(MockAPIError, match="page 2"):
        fixture.fetch_page(page=2, cursor="cursor-1")

    recovered = fixture.fetch_page(page=2, cursor="cursor-1")
    assert recovered["page"] == 2
    assert recovered["cursorBefore"] == "cursor-1"
    assert recovered["cursorAfter"] == "cursor-2"


def test_reset_viettelpay_fixture_writes_reproducible_contract(tmp_path):
    manifest_path = reset_viettelpay_fixture(tmp_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["partner"] == "VIETTELPAY"
    assert manifest["pages"] == 3
    assert [path.name for path in sorted(tmp_path.glob("page-*.json"))] == [
        "page-1.json",
        "page-2.json",
        "page-3.json",
    ]

    page = json.loads((tmp_path / "page-1.json").read_text(encoding="utf-8"))
    assert page["items"][0]["currency"] == "VND"
    assert page["items"][0]["transDate"] == "2026-08-09 12:00:00"


def test_viettelpay_mock_row_passes_seed_mapping_and_row_validation():
    fixture = ViettelPayMockFixture()
    row = fixture.fetch_page(page=1, cursor=None)["items"][0]
    config = MappingConfig.model_validate(_mapping_document(datetime.now(UTC)))

    assert ConfigValidator.validate(config) == []
    normalized = TransactionNormalizer(config.field_mappings).normalize(row, row_number=1)
    assert normalized.errors == []

    transaction, build_errors = TransactionNormalizer.build_canonical(
        normalized.data, [], row_number=1
    )
    assert build_errors == []
    assert transaction is not None
    assert Validator().validate(transaction, row_number=1, trace=transaction.trace).is_valid


def test_viettelpay_demo_mapping_template_is_not_preapproved():
    document = _mapping_document(datetime.now(UTC))

    assert document["status"] == "PENDING_APPROVAL"
    assert "approvedAt" not in document
    assert "approvedBy" not in document


@pytest.mark.asyncio
async def test_reset_wipes_viettelpay_quarantine_records():
    deletes: list[tuple[str, dict[str, str]]] = []

    class Collection:
        def __init__(self, name: str) -> None:
            self.name = name

        async def delete_many(self, query: dict[str, str]) -> None:
            deletes.append((self.name, query))

    class Database:
        def __getitem__(self, name: str) -> Collection:
            return Collection(name)

    await _wipe_mongo(Database())

    assert (
        "ingestion_quarantine_record",
        {"partner": "VIETTELPAY"},
    ) in deletes


@pytest.mark.asyncio
async def test_sprint2_evaluation_covers_failure_restart_resume_replay_and_invariant():
    report = await run_sprint2_evaluation()

    assert report["summary"] == {"total": 4, "passed": 4, "failed": 0}
    assert [scenario["id"] for scenario in report["scenarios"]] == [
        "S2-02",
        "S2-03",
        "S2-05",
        "S2-13",
    ]
    assert all(scenario["passed"] for scenario in report["scenarios"])
    assert report["finalCheckpoint"]["lastCompletedUnitKey"] == "page:3"
    assert report["finalInvariant"]["duplicateIngestionKeys"] == 0
