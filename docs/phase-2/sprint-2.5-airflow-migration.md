# Phase 2 — Sprint 2.5: Airflow Migration Plan

**Status:** Pilot implemented; production cutover pending evaluation  
**Timing:** Sau khi Sprint 2 hoàn tất và có regression evidence đầy đủ  
**Owner:** Platform/ingestion team

## Goal

Thay thế APScheduler bằng Apache Airflow ở lớp scheduling và workflow control-plane, đồng thời tái sử dụng fetcher, ingestion pipeline, checkpoint và recovery contract đã hoàn tất ở Sprint 2.

Sprint 2.5 không viết lại ingestion flow. Airflow chỉ quyết định khi nào một stream chạy, chạy theo dependency nào, retry ở cấp task ra sao và operator theo dõi workflow thế nào.

## Implemented pilot (2026-08-09)

Phạm vi đầu tiên đã được triển khai với Airflow `3.3.0`, `LocalExecutor` và một DAG generic:

- `execute_stream()` là application entrypoint chung cho Airflow và adapter local.
- `/api/v1/automation` có thể submit manual/retry run qua Airflow REST API khi `APP_AUTOMATION_ORCHESTRATOR=airflow`.
- DAG scheduled lấy danh sách config enabled; manual/backfill nhận identifier-only `conf`, không mang partner secret qua REST/XCom.
- Runtime record lưu `dagId`, `dagRunId`, `taskId`, mapped-task index, try number và logical date.
- Airflow dùng metadata database `airflow` riêng trong cùng PostgreSQL instance; không trộn metadata table vào application database.
- Pool `ingestion_streams=1`, `max_active_runs=1` và mapped stream task tuần tự giữ nguyên boundary checkpoint của Sprint 2.
- Operator backfill dùng cùng DAG với `mode=BACKFILL`: một parent run lưu
  từng business date, Airflow xử lý tuần tự, và Guided Review approval resume
  parent đó qua `backfillRunId` thay vì tạo post-approval run thứ hai.
- Schedules UI có action grid compact, dialog chọn range, và progress panel
  polling parent run; VNPAY FileDrop là fixture reproducible cho flow này.
- Compose dùng Airflow làm application orchestrator duy nhất. Manual pilot giữ
  `AIRFLOW_GLOBAL_SCHEDULE=none`; APScheduler control plane đã được decommission
  sau khi VNPAY backfill đạt 3/3 ngày `COMPLETED`.

Các file vận hành chính: `Dockerfile.airflow`, `requirements-airflow.txt`, `docker-compose.yml`, `dags/reconciliation_ingestion.py` và `docker/bootstrap-airflow-db.sh`.

### ViettelPay live pilot evidence

Pilot manual-only đã chạy qua API ứng dụng với mock API ba trang:

- Run đầu (`f68207de-3f25-44f7-b357-7881a444b65a`) persist trang 1 rồi fail đúng trang 2 sau ba HTTP 504; checkpoint giữ trang 1 `COMPLETED`, PostgreSQL có 2/2 ingestion key distinct và quarantine bằng 0.
- Recovery retry (`e2d7b6d7-a6a7-43fc-ac8a-9d65bf11f4a7`) resume từ trang 2, xử lý hai unit còn lại và kết thúc `COMPLETED`; PostgreSQL có 6/6 ingestion key distinct.
- Replay (`616e2e4a-55b4-4397-900f-8aab1e0923f6`) trả `streamAlreadyCompleted=true`, xử lý 0 unit mới và giữ nguyên 6 dòng, 0 duplicate.
- API server, scheduler và DAG processor được restart; health trở lại `healthy` và run sau restart (`c6389099-f195-4d32-8517-6de4ca0da575`) hoàn tất qua Airflow.

Trạng thái local sau pilot: API dùng `APP_AUTOMATION_ORCHESTRATOR=airflow`,
`AIRFLOW_GLOBAL_SCHEDULE=none`, và không còn service/container APScheduler.
Nút Run Now/retry/backfill trên UI đi qua Airflow; cron tự động chưa được bật
cho các partner khác trong manual pilot.

### Local startup

```bash
cp .env.example .env
docker compose build airflow-api-server
docker compose up -d postgres mongodb sftp airflow-api-server airflow-scheduler airflow-dag-processor api
docker compose ps
```

Airflow UI/API ở `http://localhost:8080`. DAG được pause khi tạo để tránh ownership kép. Với demo manual, API đã cấu hình đi qua Airflow:

```dotenv
APP_AUTOMATION_ORCHESTRATOR=airflow
AIRFLOW_GLOBAL_SCHEDULE=none
```

`none` giữ DAG ở chế độ manual-only trong pilot, vì vậy unpause DAG không tự chạy tất cả fetch config đang enabled. Chỉ đổi lại cron production sau khi có acceptance decision riêng.

### FileDrop/SFTP path contract in Airflow

Airflow task execution uses `/opt/airflow/app` as its working directory. This
matches the Airflow task mounts in `docker-compose.yml`:

- `./mock_data` → `/opt/airflow/app/mock_data`
- `./sftp_data` → `/opt/airflow/app/sftp_data`
- `./downloads` → `/opt/airflow/app/downloads`

Therefore the existing MOMO demo config (`filedrop.directory=./mock_data`) is
valid for the API (`/app`) and Airflow (`/opt/airflow/app`). The
fetchers also resolve relative paths from the application root, so task cwd
changes cannot redirect the lookup to `/opt/airflow/mock_data` or another
unmounted directory. The same contract applies to FileDrop/SFTP streams using
`./sftp_data` and the default SFTP download directory `./downloads`.
Compose runs `airflow-volume-permissions` before `airflow-init` so the
non-root Airflow worker (UID 50000, group 0) can write those bind mounts. If a
host ACL or an externally managed volume overrides the permissions, verify
that `downloads/` and `sftp_data/` are group-writable before starting the
Airflow services.
FileDrop/SFTP source units are still processed sequentially at file boundary;
mapping review is evaluated per file, not as one API-style paginated stream
packet.

`AIRFLOW_JWT_SECRET` phải có ít nhất 64 ký tự ngẫu nhiên và giống nhau trên API server, scheduler và DAG processor. Không dùng giá trị local-development mặc định khi triển khai production.

Rollback pilot là pause DAG và rollback application deployment về artifact trước
cutover nếu cần; không có đường bật lại APScheduler và không reset checkpoint
hoặc runtime data.

### Submission and outcome contract

- API tạo `runtimeRunId`, dùng DAG run ID xác định `manual__<runtimeRunId>` và submit qua `/api/v2/dags/{dag_id}/dagRuns`.
- `409` hoặc POST timeout được probe lại bằng GET; chỉ coi là idempotent khi runtime/correlation khớp.
- `COMPLETED`, `NO_DATA`, `ALREADY_PROCESSED` và `WAITING_REVIEW` kết thúc task thành công. `WAITING_REVIEW` là operator gate: application runtime giữ trạng thái chờ duyệt và review packet là nguồn hành động tiếp theo, không phải Airflow task failure/retry.
- `FAILED` và `BLOCKED` làm task fail; deployment mặc định đặt
  `AIRFLOW_TASK_RETRIES=0`, nên không có native/automatic retry. Checkpoint
  tiếp tục là nguồn sự thật để resume. Manual retry trên UI đọc mapped task bằng `task_id/map_index` rồi
  gọi `clearTaskInstances` trên chính `dagRunId` hiện tại với
  `reset_dag_runs=true`, nên DagRun terminal được đưa về `QUEUED` và không
  tạo runtime/DAG run thứ hai. Nếu task state đã là `null` do một lần clear
  cũ, gateway fallback đọc state của parent DagRun để repair cùng run. Nếu
  Airflow không đọc được task state hoặc không
  có adapter retry, API trả `409/503` và không âm thầm tạo run mới.
- Chỉ operator mới được kích hoạt retry qua **Retry now**. Không đặt giá trị
  khác `0` trong môi trường manual-only; nếu cần thay đổi policy phải có
  acceptance test riêng vì native retry sẽ tạo thêm attempt trước khi UI cập nhật.
- Với API pagination, review packet gom các `sampleRows` đã persist của cùng partner/ngày, loại trùng và giữ bounded sample; packet không còn phụ thuộc vào file download còn tồn tại trong volume.

### Airflow failure versus page recovery

Airflow đánh trạng thái ở cấp `DagRun`/mapped task, còn Schedules UI hiển thị
checkpoint theo từng source page. Vì vậy một run có thể đồng thời hiển thị
`page 1 COMPLETED`, `page 2 FAILED` ở UI và `DagRun FAILED` trên Airflow; đây là
cùng một execution boundary, không phải hai kết quả mâu thuẫn. Nút retry trên
UI clear task lỗi trong cùng `dagRunId` và resume từ checkpoint lỗi; chỉ khi
không có Airflow run đang gắn với runtime (legacy/rollback) mới dùng fallback
tạo run mới. UI hiện giữ `recentRuntimeRuns` để không làm mất lịch sử các lần
Airflow fail trước đó.

Airflow task log hiện ghi structured `stream_execution_started`,
`stream_execution_result` và `stream_execution_succeeded/exception`, gồm
`runtimeRunId`, `dagRunId`, task try, outcome, error code, checkpoint và counters.
Các log source-unit bổ sung `partner`, `fetchConfigId`, `streamKey`,
`sourceUnitKey`, page/cursor và error code. Vì vậy có thể lọc một stream bằng
`runtimeRunId` hoặc nhanh hơn bằng `partner`:

```bash
docker logs reconciliation-airflow-scheduler 2>&1 \
  | rg 'partner=VIETTELPAY|runtimeRunId=<runtime-id>'
```

### Deterministic ViettelPay manual-retry demo

Use these settings for the UI demo (the values are also present in
`.env.example`):

```dotenv
APP_AUTOMATION_ORCHESTRATOR=airflow
AIRFLOW_GLOBAL_SCHEDULE=none
AIRFLOW_TASK_RETRIES=0
AIRFLOW_TASK_RETRY_DELAY_SECONDS=300
```

Rebuild the API and Airflow image after changing the DAG or gateway code, then
make sure the DAG is unpaused. Trigger one ViettelPay run from the UI. When
the mock injects a page-2 failure, the expected flow is:

1. The UI and Airflow show the same `runtimeRunId`/`dagRunId`; no second run is
   created.
2. The UI reads
   `GET /api/v2/dags/reconciliation_ingestion/dagRuns/{dagRunId}/taskInstances/run_stream/{mapIndex}`.
3. Clicking **Manual retry** calls
   `POST /api/v2/dags/reconciliation_ingestion/clearTaskInstances` with
   `dry_run=false`, `only_failed=false`, `dag_run_id` and the mapped task pair.
4. Airflow schedules a new try of that same task instance. The UI keeps the
   same `runtimeRunId`, resumes from the checkpoint, and eventually shows the
   complete review/reconciliation result.

If the state read fails, the API now returns `409` without creating a new DAG
run and writes the Airflow endpoint details to the API log. This is an
orchestration/configuration error to fix, not a reason to use **Run Now**.

### Durable raw staging for large API streams

Đã bổ sung `raw_ingestion_page` cho API pagination:

- Payload đầy đủ nằm trong GridFS bucket `raw_ingestion`; Mongo document chỉ giữ metadata, hash, cursor, bounded `sampleRows`, trạng thái và thời hạn lưu.
- Scheduler fetch hết các page và stage theo `sourceUnitKey` trước khi chạy ingestion. Review packet chỉ được tạo sau khi page cuối xác nhận `has_more=false`; nếu page giữa stream lỗi thì chỉ giữ raw/checkpoint để retry, chưa tạo packet. Khi thiếu mapping sau khi fetch hoàn tất, stream chuyển `WAITING_REVIEW`, không ghi `partner_transaction`, nhưng raw pages vẫn còn để tạo packet đầy đủ.
- Sau approval, post-approval runner materialize từng page từ GridFS, replay qua ingestion/reconciliation hiện có và đánh dấu page `CONSUMED`. Retry upload và replay theo `sourceUnitKey` là idempotent.
- Retention mặc định là 7 ngày; daily job dọn metadata và GridFS payload hết hạn. Nếu adapter không phải Motor (test double/legacy), hệ thống giữ fallback one-page gate cũ.

## Current baseline

Repository hiện có các boundary phù hợp cho migration:

- [Scheduler jobs](../../src/scheduler/jobs.py) đang load config, gọi fetcher, xử lý pagination/file units và kết nối application orchestration.
- [Source-unit orchestrator](../../src/application/ingestion/source_unit_orchestrator.py) đã giữ checkpoint sequencing, claim, retry, completion và advance boundary.
- [Fetcher contract](../../src/fetchers/base.py) chuẩn hóa `FetchResult` và `SourceUnitMetadata` cho API, SFTP và FileDrop.
- [Sprint 2 recovery contract](sprint-2-incremental-recovery.md) yêu cầu xử lý tuần tự, checkpoint chỉ advance sau persistence thành công và backfill không làm thay đổi scheduled stream.

## Architecture decision

### Decision

Airflow là lớp trigger/orchestration bên ngoài duy nhất. Business logic ingestion vẫn thuộc application/domain/infrastructure của repository.

```text
Airflow DAG
  -> scheduling, dependency, task retry, timeout, pool
  -> application ingestion entrypoint
      -> source-unit orchestrator
          -> APIFetcher / SFTPFetcher / FileDropFetcher
          -> ingestion pipeline
          -> checkpoint repository
          -> runtime status and reconciliation
```

### Responsibility boundary

| Component | Owns | Does not own |
|---|---|---|
| Airflow | DAG schedule, task dependency, task-level retry, timeout, pool, backfill trigger, task logs | `source_unit_key`, checkpoint boundary, ingestion idempotency, business rules |
| Application service | One stream execution, fetch/ingest sequencing, runtime result contract | Global workflow scheduling |
| Fetchers | API/SFTP/FileDrop retrieval and source-unit identity | Checkpoint advancement and downstream reconciliation |
| Checkpoint repository | Claim, completed/failed/blocked state, cursor and high-water mark | Airflow task state |
| Ingestion pipeline | File claim, mapping, validation, PostgreSQL persistence and ingestion outcome | DAG scheduling |

Airflow retry không thay thế retry policy của source unit. Hai lớp phải được giới hạn rõ để tránh retry storm: application retry xử lý lỗi fetch/persist của unit; Airflow retry xử lý task/process failure hoặc restart ở cấp workflow.

## Why migrate after Sprint 2

Sau Sprint 2, migration chủ yếu là thay adapter scheduling vì các contract khó nhất đã có:

- `FetchResult` và `SourceUnitMetadata` có identity ổn định.
- Checkpoint là nguồn sự thật cho resume/replay.
- `process_source_units()` giữ sequential boundary và không advance trước persistence.
- Replay an toàn dựa trên `fileHash`, `fetchUnitKey` và `ingestion_key`.
- Scheduled stream và backfill đã có identity riêng.

Airflow vẫn không tự fetch dữ liệu. DAG phải gọi application entrypoint để application gọi `APIFetcher`, `SFTPFetcher` hoặc `FileDropFetcher`.

## Target design for the first migration

### DAG shape

Giai đoạn đầu dùng một DAG generic với task chạy từng source stream tuần tự. Task đó gọi application service hiện tại; không tách mỗi cursor page thành một Airflow task động.

Lý do:

- Giữ nguyên checkpoint boundary và failure/resume semantics của Sprint 2.
- Với API lớn, prefetch chỉ dừng ở bước lưu raw page bền vững; không prefetch vào PostgreSQL hay tạo transaction trước khi mapping được duyệt.
- Không biến Airflow metadata thành source-unit ledger thứ hai.
- Có thể pause DAG và rollback application artifact mà không đổi dữ liệu hoặc
  checkpoint.

Các tham số tối thiểu của DAG/task:

- `fetch_config_id` hoặc stream identity.
- `partner` và `reconciliation_date`.
- `mode`: `SCHEDULED` hoặc `BACKFILL`.
- `runtime_run_id` nếu được tạo từ UI/API.
- `config_version` và correlation/run identifier.

### Configuration and secrets

- `FetchConfig` vẫn là nguồn cấu hình nghiệp vụ của ứng dụng trong giai đoạn đầu.
- Airflow giữ schedule, pool và operational parameters; không copy toàn bộ partner config vào DAG source.
- Pilot nhận application credentials qua environment như stack hiện tại; partner credential không hard-code trong DAG và không ghi vào REST `conf`/XCom. Trước production cần chuyển secret distribution sang Docker/Kubernetes secrets hoặc Airflow secrets backend.
- Airflow metadata database nên là database/schema riêng với application PostgreSQL. Không dùng Airflow metadata tables làm persistence cho ingestion.

### Scheduling ownership

Trong manual pilot, Airflow là owner duy nhất cho các stream được operator kích
hoạt. DAG giữ `AIRFLOW_GLOBAL_SCHEDULE=none`, do đó không có daily trigger tự
động và không có dual-run với scheduler khác.

## Migration tasks

### Task 0 — Chốt ADR và inventory

- Ghi nhận Airflow là control-plane scheduler, không phải fetcher hay checkpoint store.
- Mapping lịch sử từ scheduler job/config/runtime status sang DAG/task/run
  metadata đã được hoàn tất trong pilot.
- Chốt Airflow major version, executor, deployment target, timezone và ownership vận hành.

**Verify:** ADR được review; không còn hai thành phần cùng sở hữu production schedule.

### Task 1 — Ổn định application entrypoint (implemented)

- Tạo một entrypoint rõ ràng cho Airflow gọi, bọc `run_fetch_config_once()` hoặc application service tương đương.
- Chuẩn hóa kết quả thành `success`, `outcome`, `errorCode`, `retryable`, checkpoint position và runtime run id.
- Bảo đảm entrypoint không phụ thuộc vào process của APScheduler.

**Verify:** gọi trực tiếp bằng CLI/test runner vẫn chạy được API pagination, FileDrop/SFTP, replay, retry và backfill isolation.

### Task 2 — Dựng Airflow development stack (implemented for local pilot)

- Thêm Airflow scheduler, API server/web UI, DAG processor/worker theo executor đã chọn và metadata PostgreSQL riêng.
- Thiết lập healthcheck, migration command, timezone, log retention và DAG deployment.
- Tạo Connections/secrets cho MongoDB, application PostgreSQL và partner endpoints theo nguyên tắc least privilege.

**Verify:** `airflow db check`, Airflow UI/API healthy, DAG parse không lỗi và application database không bị thay đổi schema ngoài migration đã duyệt.

### Task 3 — Viết pilot DAG (implemented)

- Tạo DAG generic gọi application entrypoint cho một partner/config có fixture recovery, ưu tiên ViettelPay.
- Cấu hình schedule, `execution_timeout`, bounded Airflow retries và pool slot cho từng stream.
- Propagate Airflow `dag_run_id`/`task_instance` correlation vào `partner_runtime_run` và structured logs.

**Verify:** manual run và scheduled run tạo đúng một runtime run; page/file failure dừng đúng boundary; retry tiếp tục từ checkpoint và không tạo duplicate.

### Task 4 — Contract and recovery testing (ViettelPay live pilot passed; broader matrix pending)

- Test DAG import/serialization và task parameter validation.
- Giữ regression của Sprint 1–2: failure giữa page, restart/resume, replay, duplicate invariant, FileDrop/SFTP retry và backfill isolation.
- Test Airflow retry khi process bị kill sau persistence nhưng trước task completion.
- Test timeout, missed schedule, concurrent trigger và pool saturation.

**Verify:** Airflow task retry không advance checkpoint sai, không tạo duplicate ingestion key và không chạy vượt blocked boundary.

### Task 5 — Dual-run và cutover theo partner (superseded)

- Chạy Airflow pilot ở manual/shadow mode.
- So sánh runtime status, checkpoint, row counts, duplicate count, latency và error classification giữa scheduler cũ và pilot.
- Không triển khai dual-run trong manual pilot; Airflow được xác minh trên
  fixture/ViettelPay/VNPAY và giữ manual-only để giới hạn blast radius.

**Verify:** mỗi partner có một scheduler owner duy nhất; cutover/revert không làm mất checkpoint hoặc tạo double run.

### Task 6 — Decommission APScheduler (completed for manual pilot)

- Đã xóa registration/startup path, Compose service/profile, implementation,
  dependency và Mongo `apscheduler_jobs` control-plane dependency.
- Đã cập nhật Docker Compose, CLI, README, test suite và runbook.
- Runtime history cũ vẫn giữ nguyên trong Mongo để audit; không migrate sang
  Airflow metadata.

**Verify:** production stack không còn process APScheduler; Airflow là nguồn schedule duy nhất; manual run và operator recovery vẫn hoạt động.

### Task 7 — Final verification (live pilot passed; outage matrix pending)

- Chạy full backend quality/regression suite.
- Chạy deterministic Sprint 2 evaluation và pilot Airflow evaluation.
- Kiểm tra restart Airflow, restart worker, metadata DB outage, application DB outage và partner timeout.
- Đối chiếu invariant: không duplicate ingestion key, checkpoint contiguous, blocked unit không tự skip, backfill không advance scheduled checkpoint.

**Exit criterion:** manual pilot có evidence về manual run, retry, restart và
  ordered backfill; daily cron production là follow-up riêng.

## Cutover and rollback

### Cutover

```text
Airflow manual pilot
  -> compare checkpoint/runtime/data evidence
  -> Airflow remains the only workflow owner
  -> enable production cron only after a separate acceptance decision
```

Trong pilot, không reset checkpoint và không chạy đồng thời cùng một stream từ
hai workflow owner. Nếu cần re-run, dùng cùng stream identity và dựa vào
replay-safe claim.

### Rollback

- Disable Airflow DAG cho partner bị lỗi.
- Deploy lại application artifact trước cutover và giữ DAG ở trạng thái paused.
- Không sửa hoặc lùi checkpoint bằng tay trừ khi có operator action/audit theo recovery contract.
- Kiểm tra task failure sau persistence: replay phải trả duplicate/replay outcome an toàn.

## Acceptance criteria

- [x] Airflow có thể trigger scheduled/manual run và ordered backfill run; VNPAY
  fixture/UI approval flow có regression coverage.
- [x] API pagination stage toàn bộ raw page ngoài transaction store, sau đó ingestion/replay vẫn xử lý từng page theo thứ tự và checkpoint không advance vượt persistence boundary.
- [ ] FileDrop/SFTP xử lý từng fingerprint theo thứ tự và giữ source đủ lâu cho recovery.
- [ ] Airflow retry và application retry có bounded policy, không retry vô hạn.
- [ ] `BLOCKED`, operator resolve/skip và `WAITING_REVIEW` vẫn giữ semantics hiện tại.
- [x] Thiếu approved mapping tạo review packet `PENDING`, giữ toàn bộ raw pages ngoài transaction store và không ghi partner rows; approved mapping replay đủ pages và tạo reconciliation result.
- [x] Runtime status từ `/api/v1/automation` vẫn truy vết được Airflow run/task.
- [x] Không duplicate ingestion key sau retry, restart và replay của ViettelPay pilot.
- [ ] Scheduled checkpoint không bị thay đổi bởi backfill.
- [ ] Có rollback per partner và không cần reset dữ liệu để rollback.
- [x] APScheduler đã được gỡ khỏi manual-pilot deployment sau final verification.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Airflow retry chồng với application retry | Phân loại trách nhiệm, đặt max attempts/backoff riêng và test failure matrix |
| Hai scheduler cùng trigger một stream | Dual-run chỉ manual/shadow; cutover theo partner; lock/claim vẫn là safety net |
| DAG trở thành nơi chứa business logic | DAG chỉ gọi application entrypoint; review import boundary |
| Airflow metadata và application DB bị trộn | Dùng metadata DB riêng, migration/backup riêng |
| XCom/log làm lộ credential hoặc raw payload | Connections/secrets backend; chỉ truyền identifiers/status nhỏ |
| Tách page thành task làm sai sequential recovery | Giai đoạn đầu giữ một task gọi sequential source-unit service |
| Airflow deployment trở thành bottleneck mới | Healthcheck, pool limit, worker restart test và operational runbook |

## References

- [Apache Airflow overview and distributed architecture](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html)
- [Airflow scheduler](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/scheduler.html)
- [Airflow production deployment](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/production-deployment.html)
- [Airflow pools and task concurrency](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html)
- [Repository scheduler boundary](../../README.md#architectural-boundaries)
- [Sprint 2 incremental processing and recovery](sprint-2-incremental-recovery.md)
