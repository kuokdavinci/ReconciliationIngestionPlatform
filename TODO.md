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

## Sprint 2 / 2.5 recovery hardening — 2026-08-10

Global review findings are mapped and implemented from the tracked plan in
[`docs/phase-2/sprint-2.6-recovery-hardening.md`](docs/phase-2/sprint-2.6-recovery-hardening.md).

- [x] `S26-P0-01` — Enforce a single scheduler owner between Airflow and APScheduler.
- [x] `S26-P0-02` — Persist runtime attempt history and surface pre-checkpoint
  durable-staging failures in the Recovery drawer.
- [x] `S26-P0-03` — Preserve retry history when Airflow clears a task in-place.
- [x] `S26-P1-01` — Count all raw staged API pages in review scope analysis.
- [x] `S26-P1-02` — Normalize business-day bounds to UTC and align the demo seed.
- [x] `S26-P1-03` — Mark manual runtime failures for Airflow selection/config errors.
- [x] `S26-P2-01` — Align native Airflow retry gating with configured retry budget.
- [ ] `S26-P2-02` — Complete live Airflow/DB acceptance evidence.

Đã hoàn tất toàn bộ `S2-RED-01..03` và `S2-YELLOW-01..06`; Sprint 2 review remediation đã có runtime evidence.

- [x] `MOMO-E2E-FAIL-01` — Thêm `make momo-e2e-fail` để seed MOMO với mapping
  APPROVED và file `.xlsx` hợp lệ nhưng bỏ trống cả `msTransId`/`msMaHDon`,
  phục vụ kiểm tra runtime `FAILED` do không tạo được `ingestionKey`.
- [x] `MOMO-E2E-FAIL-02` — Phân biệt `ingestion_key_error` terminal với
  `source_persist_error` retryable; file thiếu identity chuyển recovery sang
  `BLOCKED` để operator sửa file và Resolve for retry.
- [x] `MOMO-E2E-FAIL-03` — Pin `structureSignature` của file fixture vào mapping
  APPROVED để config-health không chuyển demo sang `PENDING/WAITING_REVIEW`.
- [x] `MOMO-E2E-FAIL-04` — Chuyển các target seed MOMO sang chạy trong API
  container với `/app/mock_data`, tránh lệch Mongo/Postgres và filesystem giữa
  host với scheduler Docker.

- [x] `S2-UI-DEMO-12` — Cho config-health nhận JSON pagination envelope
  `{items, nextCursor}` của ViettelPay; mapping APPROVED được bootstrap đúng ở
  lần Run Now đầu, không chuyển nhầm sang `PENDING/WAITING_REVIEW`.

## Sprint 2 — Operator recovery view plan

### Mục tiêu

Mở rộng `/schedules` thành operator recovery view để operator biết chính xác
partner đang dừng ở source unit nào, checkpoint nào đã commit, lỗi có retry được
hay không và có thể resume an toàn từ checkpoint hiện hữu. Không tạo một màn hình
Sprint 2 riêng và không đưa credential/raw payload vào response.

### Nguyên tắc triển khai

- Làm hết P0 theo thứ tự dependency rồi mới chuyển sang P1.
- `Retry now` phải resume stream từ checkpoint hiện hữu; không tạo một run mới
  bằng cách gọi lại `Run Now` một cách mù quáng.
- `FAILED`, `BLOCKED`, `WAITING_REVIEW`, `COMPLETED` và replay phải có mapping UI
  riêng, vì mỗi trạng thái yêu cầu operator action khác nhau.
- Timeline phải lấy từ read model backend có dữ liệu persisted; frontend không tự
  suy diễn lịch sử từ một `currentUnitKey`.
- Mỗi slice chỉ chạm phạm vi cần thiết, có test regression trước khi đánh dấu hoàn
  tất. Sau thay đổi dependency/structure phải kiểm tra lại codegraph.

### P0 — Recovery visibility và resume

- [x] `S2-RECOVERY-P0-01` — Chốt recovery read model và dữ liệu timeline.
  - Phạm vi: domain checkpoint, repository/mapper ingestion, schema/index nếu cần.
  - Bổ sung typed unit summary gồm `unitKey`, `label/page`, `status`, cursor
    boundary, attempt, error code và timestamps; lưu compact metadata, không lưu
    credential hoặc raw page/file payload.
  - Đảm bảo stream identity vẫn gồm partner, fetch config, source type, mode,
    stream key và config version.
  - Verify: unit timeline có thứ tự ổn định; replay không tạo duplicate unit;
    architecture test không cho API import trực tiếp Mongo model.
  - Evidence: `27 passed` cho checkpoint/scheduler/orchestrator; Ruff và mypy
    targeted pass; codegraph sync từ 5.124 lên 5.129 nodes và 12.593 edges,
    status up-to-date.
  - Review: timeline được embed cùng checkpoint để transition atomic và tương
    thích document cũ; nếu stream có rất nhiều unit cần tách read model thành
    collection riêng. Chỉ unit đã discover/claim mới có entry; P0-02 không được
    suy diễn danh sách pending khi upstream chưa cung cấp thông tin đó.

- [x] `S2-RECOVERY-P0-02` — Expose checkpoint/recovery summary từ backend.
  - Phạm vi: `src/api/automation.py`, runtime/checkpoint application service,
    `tests/test_api_automation.py`.
  - Mở rộng response `/automation/jobs` với `streamKey`, `mode`,
    `lastCompletedUnitKey`, `currentUnitKey`, `currentPage`, `cursorBefore`,
    `attemptCount`, `maxAttempts`, `retryable`, `nextRetryAt`, `errorCode`,
    `lastError` và recovery status; trả timeline compact cho detail view.
  - Verify: payload không chứa password, token, private key, raw credentials;
    thiếu checkpoint vẫn trả summary an toàn thay vì 500.
  - Evidence: `34 passed` cho checkpoint/recovery/automation/scheduler/orchestrator;
    Ruff và mypy targeted pass; response có `recovery` object backward-compatible,
    batch checkpoint lookup và redaction cho stream key/error message.
  - Review: giữ `job.status` cũ để không phá dashboard hiện tại; recovery status
    nằm trong `job.recovery.status`. Checkpoint chưa discover vẫn không được
    frontend suy diễn thành unit pending; giới hạn này chuyển sang P0-08/demo.

- [x] `S2-RECOVERY-P0-03` — Tạo endpoint resume/retry có kiểm soát.
  - Phạm vi: API route, application use case, actor/audit contract và backend
    tests.
  - `POST /automation/jobs/{partner}/recovery/retry` chỉ cho phép retry khi
    checkpoint là retryable/đã được resolve; giữ nguyên stream identity và
    tiếp tục từ failed unit. Reject conflict khi đang có claim sống và reject
    terminal `BLOCKED` nếu chưa resolve.
  - Verify: retry page 2 không xử lý lại page 1; retry thành công tiến được page
    3; retry terminal trả lỗi rõ ràng và có actor.
  - Evidence: `39 passed` cho checkpoint/recovery/automation/run/scheduler/orchestrator;
    Ruff và mypy targeted pass; codegraph status up-to-date với 5.187 nodes và
    12.754 edges.
  - Review: retry thủ công chỉ bypass backoff, không reset attempt count hoặc
    stream identity. Live claim và BLOCKED đều bị chặn; resolve BLOCKED vẫn để
    P1 vì cần reason/actor workflow riêng.

- [x] `S2-RECOVERY-P0-04` — Đồng bộ TypeScript contract và API adapter.
  - Phạm vi: `frontend-next/src/types/schedules.ts`,
    `frontend-next/src/lib/api/automation.ts`, mock schedule data.
  - Khai báo discriminated recovery types cho status, retry state, unit timeline
    và error; normalize nullable/legacy job payload tại một boundary.
  - Verify: `npx tsc --noEmit` pass; không rải string status parsing trong các
    component.
  - Evidence: frontend lint pass với 0 errors/2 existing font warnings; strict
    `npx tsc --noEmit` pass; codegraph up-to-date ở 5.203 nodes và 12.818 edges.
  - Review: normalizer đặt tại API boundary, giữ component thuần presentation;
    `retryRecovery()` đã có contract nhưng chưa được gọi từ UI cho tới P0-07.

- [x] `S2-RECOVERY-P0-05` — Hiển thị recovery summary ngay trên partner row.
  - Phạm vi: `frontend-next/src/components/schedules/schedule-table.tsx` và
    `schedules.module.css`.
  - Bổ sung progress, current unit, last completed checkpoint, attempt/retryable
    state, countdown ngắn và callback `View recovery`; giữ `Run Now` cho manual
    trigger thông thường.
  - Verify: row FAILED retryable, BLOCKED, WAITING_REVIEW, COMPLETED và replay
    đều có nội dung phân biệt; layout không làm mất action hiện tại.
  - Evidence: frontend lint pass với 0 errors/2 existing warnings; strict
    TypeScript và Webpack production build pass; codegraph up-to-date ở 5.206
    nodes và 12.826 edges.
  - Review: summary dùng một status badge, tabular numbers và error-code line để
    giữ table đọc được; callback đã có ở component boundary, side panel/action
    behavior sẽ được nối ở P0-06.

- [x] `S2-RECOVERY-P0-06` — Xây side panel “Recovery details”.
  - Phạm vi: component mới dưới `frontend-next/src/components/schedules/`, page
    state trong `frontend-next/src/app/schedules/page.tsx`, CSS/UI primitives.
  - Hiển thị status, stream/mode, checkpoint, cursor, attempt, next retry, lỗi và
    timeline `COMPLETED → FAILED → WAITING`; không điều hướng sang page mới.
  - Verify: panel mở/đóng bằng keyboard, refresh dữ liệu không làm mất partner
    đang xem, timeline rỗng/thiếu dữ liệu có empty state rõ ràng.
  - Evidence: side panel hiển thị metadata, timeline, error và empty state; mở từ
    callback trên partner row, đóng bằng close/Escape/overlay, khóa scroll nền;
    frontend lint 0 errors/2 existing font warnings, strict TypeScript và
    Webpack production build pass; codegraph 368 files, 5.219 nodes, 12.848
    edges, status up-to-date.
  - Review: selection chỉ lưu partner key và derive từ jobs mới nên refresh không
    làm mất context, không dùng effect setState gây cascading render. Retry action
    được giữ làm extension point và sẽ nối ở P0-07.

- [x] `S2-RECOVERY-P0-07` — Kết nối `Retry now`, refresh và countdown.
  - Phạm vi: schedules page/API adapter/component action state.
  - Disable action khi request đang chạy, hiển thị optimistic queued state có
    kiểm soát, poll lại sau retry và cập nhật countdown theo `nextRetryAt` mà
    không tạo interval leak.
  - Verify: retry success cập nhật page 2/page 3 và duplicate count; lỗi 409,
    4xx/5xx đều có toast/actionable message.
  - Evidence: `retryRecovery()` đã nối vào side panel; nút disable khi request
    chạy, success toast rồi refresh và bounded polling tối đa 4 lần; lỗi từ
    backend client (gồm 409/4xx/5xx detail) hiển thị actionable toast. Countdown
    dùng component riêng với timer cleanup và tự dừng khi retry available.
    Frontend lint 0 errors/2 existing font warnings, strict TypeScript,
    Webpack production build và Playwright CI smoke `2 passed`; codegraph 369
    files, 5.226 nodes, 12.863 edges, status up-to-date.
  - Review: polling dùng timeout bounded có cleanup khi unmount/thay retry,
    không tạo interval vô hạn; retry giữ selection panel qua refresh. Runtime
    page 2/page 3 và duplicate count cần được chứng minh bằng fixture/demo ở
    P0-08, không suy diễn từ UI response.

- [x] `S2-RECOVERY-P0-08` — Hoàn thiện status semantics và Sprint 2 UI demo.
  - Phạm vi: status mapper backend/frontend, deterministic fixture dưới
    `scripts/demo/sprint2/`, Playwright smoke scenario và docs demo.
  - Kịch bản: seed ViettelPay 3 pages → Run Now → page 1 completed → page 2
    timeout → UI hiển thị page 3 waiting → Retry now → page 2/3 completed,
    checkpoint cuối page 3, duplicate count bằng 0.
  - Verify: backend evaluation pass; Playwright kiểm tra row, panel, retry và
    recovery completed; không coi replay là failure.
  - Evidence: `QUEUED`/runtime-active được map về `PROCESSING`, `duplicateCount`
    được expose an toàn từ runtime stats; recovery/API tests `10 passed` với
    Ruff và mypy pass. Deterministic ViettelPay evaluation `4/4`, Playwright
    full smoke `3 passed`; UI kiểm tra FAILED page 2 → Retry now → PROCESSING →
    COMPLETED page 3, duplicate count `0`, Escape đóng panel. Codegraph 369
    files, 5.228 nodes, 12.869 edges, status up-to-date.
  - Review: status mapper không để `QUEUED` rơi về IDLE; duplicate count lấy từ
    persisted runtime stats và mặc định an toàn về 0. UI fixture mock tách khỏi
    backend production, còn deterministic backend fixture chứng minh resume và
    không duplicate ingestion key.

### P1 — Operator workflow mở rộng

- [x] `S2-RECOVERY-P1-01` — Bộ lọc theo `FAILED`, `BLOCKED`, `WAITING_REVIEW`,
  `PROCESSING` và `COMPLETED`; giữ filter state trong URL nếu phù hợp.
  - Verify: filter không làm thay đổi backend state và không phá polling/action
    trên các row đang hiển thị.
  - Evidence: select filter trên `/schedules` dùng query param `recovery`, có
    empty state riêng khi không match; Playwright kiểm tra `FAILED` URL filter,
    `COMPLETED` empty state và sau đó vẫn mở/retry được row. Frontend lint 0
    errors/2 existing warnings, strict TypeScript và production build pass;
    codegraph 369 files, 5.234 nodes, 12.881 edges, status up-to-date.
  - Review: filter chỉ derive `filteredJobs`, metrics/recent output vẫn giữ
    toàn bộ dataset; `useSearchParams` nằm trong Suspense boundary để static
    build không fail; query param giữ được context khi refresh/back navigation.

- [x] `S2-RECOVERY-P1-02` — Recovery aggregate và event timeline.
  - Bổ sung view tổng hợp nhiều partner, event timeline chi tiết, resolve/skip có
    reason + actor và link tới raw page/file đã được sanitize.
  - Verify: audit trail có actor/reason/time; quyền truy cập và dữ liệu nhạy cảm
    được kiểm tra; chỉ triển khai sau khi P0 có runtime evidence ổn định.
  - Evidence: backend read model thêm event timeline từ persisted unit/resolution
    metadata; `POST /automation/jobs/{partner}/recovery/resolve` bắt buộc actor,
    action `RETRY|SKIP`, reason tối đa 500 ký tự và ghi audit entity key đã
    sanitize. `29 passed` cho checkpoint/recovery/automation tests; Ruff/mypy
    pass. UI có aggregate Failed/Blocked/Waiting Review, event timeline,
    BLOCKED resolve/skip form và sanitized error display; frontend lint 0
    errors/2 existing warnings, strict TypeScript/build pass; full Playwright
    `3 passed`; codegraph 369 files, 5.245 nodes, 12.931 edges, up-to-date.
  - Review: resolve không tự queue run, tránh biến operator decision thành side
    effect; `SKIP` được orchestrator hiện có consume qua resolution metadata,
    `RETRY` quay lại flow retry có kiểm soát. UI đóng panel trước khi đổi
    partner; event reason/error được redacted ở read model, không trả raw payload.

### Quality gates cho toàn bộ plan

- [x] Chạy targeted backend tests cho checkpoint, automation API, retry/resume và
  status mapping.
- [x] Chạy frontend lint, `npx tsc --noEmit`, production build và Playwright E2E.
- [x] Chạy full test suite, Ruff và mypy theo policy hiện tại.
- [x] Chạy Sprint 2 deterministic evaluation và đối chiếu duplicate count bằng 0.
- [x] Kiểm tra `codegraph status`; chỉ cập nhật index khi có thay đổi symbol,
  import hoặc dependency, sau đó ghi evidence vào TODO.

#### Quality gate evidence — 2026-08-06

- Backend targeted: `29 passed`; full suite: `925 passed, 14 skipped`, còn 1
  deprecation warning Starlette/httpx hiện hữu.
- Ruff `src scripts tests`: pass; mypy `src scripts tests`: pass trên 272 files,
  chỉ còn các note về untyped test bodies.
- Frontend lint: 0 errors/2 existing font warnings; strict TypeScript và
  Webpack production build pass; full Playwright smoke: `3 passed`.
- Sprint 2 deterministic ViettelPay evaluation: `4/4`, duplicate ingestion keys:
  `0`.
- Codegraph sau thay đổi cuối: 369 files, 5.247 nodes, 12.935 edges; status
  up-to-date.

### Real UI demo slice — DB-backed Sprint 2

- [x] `S2-UI-DEMO-01` — Cho phép JSON reader đọc response pagination dạng
  `{items, nextCursor}` nhưng vẫn giữ tương thích với JSON array; test riêng
  cho envelope đã pass.
- [x] `S2-UI-DEMO-02` — Seed demo thật cho VIETTELPAY: wipe dữ liệu test theo
  partner ở Mongo/Postgres, seed 6 internal transactions, mapping APPROVED và
  API fetch config; chưa tạo checkpoint trước Run Now.
- [x] `S2-UI-DEMO-03` — `reset` arm mock HTTP source page 1–3 với failure
  budget page 2. Run Now thủ công sẽ xử lý page 1 rồi fail ở page 2; checkpoint
  timeline lúc này mới được tạo từ runtime thật.
- [x] `S2-UI-DEMO-04` — `phase2` chỉ chuyển mock API sang no-failure, không tự
  gọi Run/Job/Retry. Retry now thủ công sẽ resume page 2 → page 3.
- [x] `S2-UI-DEMO-05` — Docker-native seed: `scripts/` được đóng gói vào API,
  scheduler và mock image; `fetch_config` được seed bằng `docker compose exec`
  vào đúng MongoDB container với `fetchMethod=API`, endpoint dùng service name
  `viettelpay-mock` thay vì loopback container.
- [x] `S2-UI-DEMO-06` — Đồng bộ Mongo credentials giữa `.env`, `api`,
  `scheduler` và `mongodb`; sửa healthcheck Compose để biến credentials được
  resolve bên trong container, tránh Mongo bị coi là unhealthy và chặn API/
  scheduler khởi động.
- [x] `S2-UI-DEMO-07` — `viettelpay-sprint2-reset` không build/restart service;
  chỉ chạy seed trong API container đang hoạt động để xoá và tạo lại dữ liệu
  ViettelPay cần cho mock.
- [x] `S2-UI-DEMO-08` — Sửa lỗi page 1 fail ngay ở `0/1`: ConfigValidator
  công nhận `sourceField` là nguồn hợp lệ cho required JSON/API mappings;
  thêm regression test để seed mapping ViettelPay không bị loại trước khi
  normalizer chạy.
- [x] `S2-UI-DEMO-09` — `viettelpay-sprint2-reset` tự khởi động
  `viettelpay-mock` sau khi seed và arm failure page 2; operator chỉ cần
  chạy reset rồi bấm `Run Now` trên UI, không cần lệnh mock riêng.
- [x] `S2-UI-DEMO-10` — Schedules UI poll theo đúng `runtimeRunId` đến khi run
  kết thúc, áp dụng cho cả `Run Now` và `Retry now`; progress API dùng
  `maxPages` để hiển thị `1/3` dù page 3 chưa discover trước lỗi page 2.
- [x] `S2-UI-DEMO-11` — Lọc process status trên Scheduler: các stage nội bộ
  `QUEUED/FETCHING/INGESTING/RECONCILING` được gom thành `RUNNING`, bỏ badge
  outcome trùng lặp và chỉ giữ `Enabled`, runtime state và recovery state.
- [x] Review slice: backend `13 passed`; frontend TypeScript và ESLint pass.
  Playwright/dev server chưa chạy được trong sandbox vì bind local port bị
  từ chối (`listen EPERM`); cần xác nhận lại trên Docker/dev environment.
- [x] Review slice: `17 passed` cho JSON pagination, fetch config, state
  transition reset/phase2 và mock failure budget; Ruff/mypy targeted pass.
  Codegraph sau sync: 371 files, 5.313 nodes, 13.105 edges; status up-to-date.
- [x] Final code-only gate sau slice: full backend suite `879 passed, 6
  skipped`, 1 warning hiện hữu; Ruff toàn `src scripts tests` pass và mypy
  toàn bộ pass.
- [ ] Live verification trên local Mongo/Postgres/API/scheduler: chưa chạy
  được trong sandbox hiện tại vì Docker socket bị từ chối và kết nối DB local
  không hoàn tất; cần chạy hai lệnh ở môi trường dev có services đang up.

### Dependency order

`P0-01 → P0-02 → P0-04 → P0-05 → P0-06 → P0-07 → P0-08`; `P0-03` cần hoàn
thành trước `P0-07`. Chỉ bắt đầu `P1-01..02` sau khi toàn bộ P0 có test/runtime
evidence.
