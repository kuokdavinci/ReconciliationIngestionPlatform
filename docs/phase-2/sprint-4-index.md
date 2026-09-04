# Sprint 4 — Index Observability

**Trạng thái:** `closed — no candidate promoted`

Sprint 4 đóng observability cho ingestion runtime trên Schedules. Các thay đổi
giữ nguyên ingestion semantics, recovery/retry và production defaults.

| Tài liệu | Vai trò | Nội dung |
|---|---|---|
| [Observability](sprint-4-observability.md) | Chính | Runtime contract, Schedules UI, warning hardening và acceptance. |
| [Baseline review 100k](sprint-4-benchmark-review-100k.md) | Evidence | Baseline latency/RSS và component median. |
| [A/B benchmark 100k](sprint-4-benchmark-ab-100k.md) | Evidence | Ma trận variant và correctness/promotion decision. |
| [Quyết định performance](sprint-4-benchmark-optimization-2.md) | Quyết định | SQL review, memory gate và baseline handoff. |

## Kết quả chính

| Hạng mục | Kết quả |
|---|---|
| Telemetry | `stageSummary` persist counter, stage, quality, checkpoint và batch timings; có `parseRowsMs`, `normalizeMs`, `validateMs`. |
| Write hardening | `INGESTION_OBSERVABILITY_WRITE_FAILED` có context bounded, không làm fail ingestion. |
| Schedules | Có current stage/outcome, last snapshot, durations, counters, quality/error và legacy fallback. |
| Review/recovery | Config review được phân biệt với active runtime error; terminal projection và retry/recovery giữ nguyên. |
| Performance | Không có SQL/memory candidate đạt gate; baseline được giữ nguyên. |

## Ranh giới đã khóa

- Không tạo Operations page mới, không đổi taxonomy, schema/index/migration,
  production default hoặc `fast_mode`.
- Snapshot active là boundary-level theo source unit hoặc terminal, không phải
  write sau từng batch.
- `FINALIZING` chỉ còn là telemetry boundary; UI dùng terminal outcome rõ ràng
  để tránh hiểu nhầm stage vẫn đang chạy.

Xem [Phase 2 index](INDEX.md) để biết vị trí Sprint 4 trong toàn phase.
