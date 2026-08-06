import json

import pytest

from scripts.demo.sprint2.evaluation import run_sprint2_evaluation
from scripts.demo.sprint2.fixture import (
    MockAPIError,
    ViettelPayMockFixture,
    reset_viettelpay_fixture,
)


def test_viettelpay_fixture_exposes_three_cursor_pages_and_controlled_failure():
    fixture = ViettelPayMockFixture(fail_once_page=2)

    first = fixture.fetch_page(page=1, cursor=None)
    assert first["page"] == 1
    assert first["cursorAfter"] == "cursor-1"
    assert first["items"]

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
