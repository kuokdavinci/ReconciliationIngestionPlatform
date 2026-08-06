# Sprint 2 Incremental Recovery Evaluation

- Evidence type: `deterministic in-memory mock; no production database mutation`
- Generated at: `2026-08-05T02:15:17.341046+00:00`
- Summary: `4/4 passed`, `0 failed`

| Scenario | Expected | Actual | Passed | Duration (ms) |
|---|---|---|---:|---:|
| S2-02 — Failure giữa page 2 | page 1 completed và stream dừng tại page 2 | processed=1, stoppedAt=page:2 | True | 0.116 |
| S2-03 — Restart và resume | chạy tiếp từ page 2, sau đó page 3 | processed=2, units=['page:2', 'page:3'] | True | 0.023 |
| S2-05 — Cursor/page replay | unit đã completed không ingest lần hai | replayed=1 | True | 0.006 |
| S2-13 — Data invariant | không có duplicate ingestion key sau recovery | ingestedKeys=['page:1', 'page:2', 'page:3'], duplicateCount=0 | True | 0.001 |

## Final checkpoint

- Status: `DISCOVERED`
- Last completed unit: `page:3`
- Cursor after: `None`
- Duplicate ingestion keys: `0`
