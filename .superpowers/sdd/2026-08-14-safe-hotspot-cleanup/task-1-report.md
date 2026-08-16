Status: completed

Summary:
- Moved Mapping Studio handoff `ReviewPacket` construction from `src/api/review_packets.py` into `src/application/review/proposal_creation.py`.
- Added `create_studio_handoff_review_packet(mapping, mapping_id, packet_repo)` and kept the route responsible only for loading the mapping, delegating creation, and serializing the returned packet.
- Added boundary coverage to assert the router delegates Studio handoff packet creation to the application layer.
- Added an application-level test with an in-memory repository fake to verify the created packet preserves `STUDIO_HANDOFF`, partner, `draftMappingId`, `fileName`, parse-strategy field count, risk summary, and recommended action.

Red-green evidence:
- RED: `uv run pytest tests/test_review_application_boundaries.py tests/test_api_review_packets.py -q` failed in the new boundary test because `src/api/review_packets.py` did not reference `create_studio_handoff_review_packet`, and failed in the new application test because `src.application.review.proposal_creation.create_studio_handoff_review_packet` did not exist.
- GREEN: the same scoped pytest command passed after the implementation change.

Verification:
- `uv run pytest tests/test_review_application_boundaries.py tests/test_api_review_packets.py -q` → 37 passed in 0.50s
- `uv run ruff check src/application/review/proposal_creation.py src/api/review_packets.py tests/test_review_application_boundaries.py tests/test_api_review_packets.py` → passed
- `git diff --check -- src/application/review/proposal_creation.py src/api/review_packets.py tests/test_review_application_boundaries.py` → passed

Files changed:
- `src/application/review/proposal_creation.py`
- `src/api/review_packets.py`
- `tests/test_review_application_boundaries.py`

Concerns:
- No functional concerns from the scoped verification.
- I did not refresh the codegraph index because this task moved logic within existing modules and did not add new files or dependency edges that require a refresh for correctness.
