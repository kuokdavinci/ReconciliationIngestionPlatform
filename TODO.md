# TODO — Phase 2 Refactor Roadmap

Mục tiêu: làm cho ingestion pipeline của Phase 2 dễ trace, dễ test và tuân theo
Clean Architecture mà không thay đổi behavior idempotency hiện tại.

## Quy ước follow từng slice

Mỗi slice phải có:

- một trách nhiệm chính;
- phạm vi file rõ ràng;
- regression test trước/sau refactor;
- Ruff + mypy targeted pass;
- codegraph sync sau khi thay đổi dependency/structure.

Không đánh dấu `[x]` nếu chỉ compile hoặc import được; phải có test/runtime evidence.

## Baseline đã hoàn thành

- [x] `S1-01` — Sửa Mapping Studio Step 4: API route, error handling, runtime polling và ingestion/reconciliation race.
- [x] `S1-02` — Fresh/existing PostgreSQL đều chạy Alembic upgrade head; thêm migration regression test.
- [x] `S1-03` — Chọn PostgreSQL làm source of truth cho `internal_transaction`; loại bỏ dual-write MongoDB trên production path.
- [x] `S1-04` — Tách reconciliation ports/use case/adapters; API, scheduler và review flow dùng application service.
- [x] `S1-05` — Tách ingestion ports/composition root; scheduler/review flow dùng ingestion factory.
- [x] `S1-06` — Di chuyển workflow models/repositories/indexes khỏi `src/models` sang domain/infrastructure bounded contexts.
- [x] `S1-07` — Production imports đã migrate khỏi compatibility shims; facade chỉ còn phục vụ legacy tests/integrations.
- [x] `S1-08` — Chốt lineage bất biến cho replay duplicate; không rebind canonical transaction; lưu `duplicateRows`.
- [x] `S1-09` — Thay `datetime.utcnow()` trong production bằng UTC-aware timestamps.
- [x] `S1-10` — Fix injectable reconciliation seam và polling race của Step 4.

## Phase 2 — Pipeline decomposition

### Đã hoàn thành

- [x] `P2-PIPE-01` — Tách pipeline slice 1:
  - `FileClaimService`: file hash, fetch-unit key và atomic claim.
  - `ConfigPreparationService`: mapping/config health/approval.
  - `RowProcessor`: normalize → validate → build canonical transaction.
  - `BatchWriteCoordinator`: giới hạn concurrent batch writes.
  - `IngestionPerformance`: format performance metrics.
  - Bỏ `print(PERF_INGEST)`, chỉ ghi qua logger.
  - Chuyển date interpolation thành pure helper trong `src/core`.

### Đã hoàn thành

- [x] `P2-PIPE-02` — Dọn composition root của `IngestionPipeline`.
  - Pipeline không còn import hoặc tự tạo concrete repositories.
  - `src/infrastructure/ingestion/composition.py` là nơi wiring production adapters.
  - Giữ injectable repository ports cho fake/test adapters.
  - Pipeline fail fast nếu thiếu port bắt buộc; duplicate/config failure vẫn có thể kết thúc sớm.
  - Đã migrate benchmark scripts sang `build_ingestion_pipeline()`.
  - Regression: 41 ingestion/architecture/integration tests pass; Ruff và mypy pass.

### Slice tiếp theo

- [x] `P2-PIPE-03` — Tách ingestion run state và batch accounting.
  - Di chuyển counters `success/failed/duplicate`, errors và ingestion keys vào state object.
  - Di chuyển `_record_batch_result()` khỏi `IngestionPipeline`.
  - Không thay đổi `BatchInsertResult` hoặc duplicate outcome contract.

- [x] `P2-PIPE-04` — Tách finalization lifecycle.
  - Tạo `IngestionRunFinalizer.complete()` và `.fail()`.
  - Gom update stats/status, lifecycle events và partial failure handling.
  - `process_file()` chỉ gọi finalizer, không lặp success/failure persistence.

- [x] `P2-PIPE-05` — Tách application input/output contracts.
  - Di chuyển `IngestionResult` ra application ingestion contract.
  - Chuẩn hóa `ProcessFileCommand` thay cho danh sách arguments dài.
  - Giữ compatibility wrapper cho caller cũ trong thời gian chuyển tiếp.

- [x] `P2-PIPE-06` — Chuẩn hóa stage observability.
  - Stage: `CLAIMING`, `CONFIGURING`, `READING`, `PROCESSING`, `PERSISTING`, `FINALIZING`.
  - Gắn `run_id`, `source_file_id`, stage và error code.
  - Không dùng `print`; structured logger là output duy nhất.

- [x] `P2-PIPE-07` — Test matrix cho pipeline components.
  - [x] Unit test riêng cho claim/config/row processor/batch writer/finalizer.
  - [x] Integration test cho file replay, fetch-unit replay, partial duplicate và failure.
  - [x] Chạy benchmark 20 records và 100k records sau thay đổi concurrency.
    - 20 records: 3 E2E tests pass.
    - 100k records: 3 E2E tests pass; adapter đã chunk INSERT theo bind-parameter limit.

## Phase 2 — Recovery, data quality và observability

- [x] `P2-REC-01` — Verify checkpoint/source-unit recovery với pipeline components mới.
- [x] `P2-REC-02` — Đảm bảo retry sau persistence failure không tạo duplicate transaction.
- [x] `P2-DQ-01` — Chuẩn hóa counters: input, persisted, rejected, duplicate, failed.
- [x] `P2-DQ-02` — Thiết kế quarantine contract cho invalid rows; không đưa validation error vào log-only path.
- [x] `P2-OBS-01` — Persist stage summary trong runtime/file record.
- [x] `P2-OBS-02` — Thêm operational query/API read-only khi stage metrics đã ổn định.

## Quality gates

- [x] `QG-01` — `ruff check src` pass.
- [x] `QG-02` — `mypy src` pass trên 162 source files.
- [x] `QG-03` — Codegraph reindex và status up-to-date sau các thay đổi pipeline/repository mới.
  - 362 files, 5,117 nodes, 12,562 edges; `codegraph status` báo index up to date.
- [x] `QG-04` — Regression tests mục tiêu cho ingestion, lineage, logging và architecture pass khi chạy độc lập.
- [x] `QG-05` — Chạy full repository test suite ổn định, không treo do test/resource lifecycle.
  - `911 passed, 14 skipped` trong 12.26s; còn 1 deprecation warning Starlette/httpx.
  - Host dependencies đã đồng bộ Docker: FastAPI 0.141.1, Starlette 1.3.1; test chạy ở runtime host ngoài sandbox.
- [x] `QG-06` — Ruff/mypy policy cho toàn bộ scripts, tests và legacy integration fixtures.
  - Ruff toàn bộ `scripts tests` đã pass.
  - Mypy `scripts tests` pass trên 101 source files; chỉ còn các note về untyped test bodies.

## Legacy migration và examples

- [x] `LEG-01` — Migrate benchmark/E2E fixture còn đọc/ghi trực tiếp MongoDB `internal_transaction` nếu vẫn được sử dụng.
  - Benchmark 1M và E2E 20/100k dùng `InternalTransactionRepository` PostgreSQL.
  - `scripts/sync_internal_transactions.py` là migration utility duy nhất còn đọc collection legacy.
- [x] `LEG-02` — Giảm imports từ `src.models.*` trong tests cho bounded contexts đã migrate.
  - Ingestion, checkpoint, source-unit, pagination và reconciliation tests đã dùng domain/infrastructure modules.
  - Các import còn lại chỉ thuộc model/facade compatibility, architecture guard hoặc migration-era tests.
- [x] `EX-01` — Tạo ví dụ fetch API pagination từng trang với cursor, replay boundary và failure/resume.
  - Xem `docs/phase-2/ingestion-pagination-example.md` và Sprint 2 deterministic fixture.

## Sprint 2 review remediation — 2026-08-06

### P đỏ — đã xử lý

- [x] `S2-RED-01` — Chỉ cleanup/archive source sau khi `mark_completed` và checkpoint `advance` thành công.
  - Cleanup được gọi qua completion hook của `process_source_units`.
  - Nếu checkpoint chưa commit, source vẫn còn để replay/recovery.
- [x] `S2-RED-02` — Bảo vệ checkpoint boundary không bị lùi.
  - `claim_unit()` nhận `expected_previous_unit_key` và dùng compare-and-set theo boundary.
  - Orchestrator truyền boundary liên tục giữa các source unit.
- [x] `S2-RED-03` — Bounded retry xuyên suốt API source-unit flow.
  - Failed network/timeout/HTTP/parse unit giữ `errorCode` riêng.
  - Stale processing claim bị giới hạn bởi `max_attempts`; exhausted claim chuyển `BLOCKED`.
  - Parse error và repeated cursor không còn bị phân loại thành network error.

### P vàng — đã xử lý

- [x] `S2-YELLOW-01` — Xóa `_run_fetch_config_legacy` không có caller theo codegraph; giảm `jobs.py` từ 980 xuống 738 dòng.
- [x] `S2-YELLOW-02` — Thêm `configVersion` vào API/FileDrop/SFTP source-unit identity và regression tests.
- [x] `S2-YELLOW-03` — Không block event loop khi FileDrop kiểm tra file ổn định; chuyển blocking check sang worker thread.
- [x] `S2-YELLOW-04` — SFTP không còn tự động trust host key; dùng system host keys và `RejectPolicy`.

### P vàng — hoàn tất

- [x] `S2-YELLOW-05` — Đưa core source-unit orchestration vào `src/application/ingestion/source_unit_orchestrator.py`; scheduler chỉ giữ compatibility facade và production job import application service.
  - `CheckpointRepository` protocol vẫn là port; architecture regression test xác nhận facade identity.
- [x] `S2-YELLOW-06` — Gỡ production CLI imports khỏi `src.models`; CLI dùng trực tiếp domain/infrastructure bounded contexts. Các facade còn lại chỉ phục vụ legacy integrations/architecture tests.

### Evidence của remediation

- 41 targeted Sprint 2/recovery/API/scheduler tests pass sau P đỏ + P vàng.
- Full suite: 911 passed, 14 skipped, 1 Starlette/httpx deprecation warning.
- Ruff và mypy targeted pass; Sprint 2 deterministic demo 4/4 pass.

## Current focus

Đã hoàn tất toàn bộ `S2-RED-01..03` và `S2-YELLOW-01..06`; Sprint 2 review remediation đã có runtime evidence.
