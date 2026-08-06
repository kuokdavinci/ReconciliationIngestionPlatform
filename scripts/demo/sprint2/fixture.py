"""Config-shaped ViettelPay mock API contract for Sprint 2 evaluation."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class MockAPIError(RuntimeError):
    """Controlled mock API failure or invalid cursor request."""


class ViettelPayMockFixture:
    """Three-page cursor fixture with deterministic, controllable failures."""

    def __init__(self, *, fail_once_page: int | None = None):
        self.fail_once_page = fail_once_page
        self._failed_pages: set[int] = set()
        self._pages: dict[int, dict[str, Any]] = {
            1: {
                "page": 1,
                "cursorBefore": None,
                "cursorAfter": "cursor-1",
                "items": [
                    {"id": "VTP-001", "amount": "100000", "status": "SUCCESS"},
                    {"id": "VTP-002", "amount": "200000", "status": "SUCCESS"},
                ],
            },
            2: {
                "page": 2,
                "cursorBefore": "cursor-1",
                "cursorAfter": "cursor-2",
                "items": [
                    {"id": "VTP-003", "amount": "300000", "status": "SUCCESS"},
                    {"id": "VTP-004", "amount": "400000", "status": "SUCCESS"},
                ],
            },
            3: {
                "page": 3,
                "cursorBefore": "cursor-2",
                "cursorAfter": None,
                "items": [
                    {"id": "VTP-005", "amount": "500000", "status": "SUCCESS"},
                    {"id": "VTP-006", "amount": "600000", "status": "SUCCESS"},
                ],
            },
        }

    def fetch_page(self, *, page: int, cursor: str | None) -> dict[str, Any]:
        if page not in self._pages:
            raise MockAPIError(f"unknown page {page}")

        expected_cursor = self._pages[page]["cursorBefore"]
        if cursor != expected_cursor:
            raise MockAPIError(
                f"invalid cursor for page {page}: expected {expected_cursor!r}"
            )
        if self.fail_once_page == page and page not in self._failed_pages:
            self._failed_pages.add(page)
            raise MockAPIError(f"controlled failure on page {page}")
        return deepcopy(self._pages[page])

    def source_units(self) -> list[dict[str, Any]]:
        """Return checkpoint-ready units without coupling the fixture to a fetcher."""

        return [
            {
                "sourceUnitKey": f"page:{page}",
                "sourceIdentity": {
                    "endpoint": "mock://viettelpay/settlement",
                    "page": page,
                    "cursorBefore": data["cursorBefore"],
                },
                "page": page,
                "cursorBefore": data["cursorBefore"],
                "cursorAfter": data["cursorAfter"],
                "highWaterMark": {"page": page, "cursorAfter": data["cursorAfter"]},
                "localPath": f"mock://viettelpay/page-{page}.json",
                "items": deepcopy(data["items"]),
            }
            for page, data in self._pages.items()
        ]


def reset_viettelpay_fixture(output_dir: str | Path) -> Path:
    """Write a clean local fixture directory and return its manifest path."""

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    fixture = ViettelPayMockFixture()
    for unit in fixture.source_units():
        page = unit["page"]
        (target / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "page": page,
                    "cursorBefore": unit["cursorBefore"],
                    "cursorAfter": unit["cursorAfter"],
                    "items": unit["items"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    manifest = {
        "partner": "VIETTELPAY",
        "endpoint": "mock://viettelpay/settlement",
        "pages": 3,
        "fixtureVersion": "sprint-2-v1",
    }
    manifest_path = target / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path
