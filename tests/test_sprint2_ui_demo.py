"""Contract tests for the real DB-backed Sprint 2 UI demo setup."""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.demo.sprint2.mock_api import MockAPIState, page_response, write_state
from scripts.demo.sprint2.seed import API_ENDPOINT, _fetch_config, _reset_local_demo_files


def test_fetch_config_matches_paginated_mock_contract() -> None:
    config = _fetch_config(datetime.now(UTC))

    assert config.api is not None
    assert config.api.base_url == API_ENDPOINT
    assert config.api.pagination is not None
    assert config.api.pagination.items_path == "items"
    assert config.api.pagination.next_cursor_path == "nextCursor"
    assert config.api.pagination.max_pages == 3


def test_reset_arms_page_two_failure_and_phase2_disarms_it(tmp_path) -> None:
    state_file = tmp_path / "mock_api_state.json"
    write_state(state_file, failures=3)
    state = MockAPIState(0, state_file=state_file)

    failed_status, failed_payload = page_response(
        state, page=2, cursor="cursor-1"
    )
    assert failed_status == 504
    assert failed_payload["error"] == "fetch_timeout"

    write_state(state_file, failures=0)
    success_status, success_payload = page_response(
        state, page=2, cursor="cursor-1"
    )
    assert success_status == 200
    assert [item["id"] for item in success_payload["items"]] == [
        "VTP-003",
        "VTP-004",
    ]
    assert success_payload["nextCursor"] == "cursor-2"


def test_mock_api_http_contract_exposes_next_cursor_for_page_one() -> None:
    state = MockAPIState(0)

    status, payload = page_response(state, page=1, cursor=None)

    assert status == 200
    assert payload["nextCursor"] == "cursor-1"
    assert "cursorAfter" not in payload


def test_reset_local_files_removes_only_generated_fixture_artifacts(tmp_path) -> None:
    (tmp_path / "page-1.json").write_text("old")
    (tmp_path / "manifest.json").write_text("old")
    (tmp_path / "keep.txt").write_text("keep")

    _reset_local_demo_files(tmp_path)

    assert not (tmp_path / "page-1.json").exists()
    assert not (tmp_path / "manifest.json").exists()
    assert (tmp_path / "keep.txt").exists()


def test_mock_api_consumes_three_http_failures_then_returns_page_two() -> None:
    state = MockAPIState(3)
    responses = [
        page_response(state, page=2, cursor="cursor-1")
        for _ in range(4)
    ]
    assert [status for status, _ in responses] == [504, 504, 504, 200]
    assert [item["id"] for item in responses[-1][1]["items"]] == [
        "VTP-003",
        "VTP-004",
    ]
