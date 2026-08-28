# Phase 2 — Sprint 2.5: Airflow và Recovery Hardening

**Trạng thái:** Đã triển khai pilot; image API hiện tại và sức khỏe Compose local được kiểm chứng ngày 2026-08-14; còn 5 tiêu chí business acceptance ở trạng thái partial hoặc pending.
**Thời điểm:** Sau khi Sprint 2 hoàn tất và có regression evidence đầy đủ
**Owner:** Platform/ingestion team

> Sprint 2.5 là milestone hợp nhất của **Airflow integration** và **recovery hardening**. Sprint 2.6 không còn là sprint độc lập; toàn bộ acceptance, implementation và evidence của phần này nằm trong tài liệu hiện tại.

**Acceptance status:** Chưa hoàn tất. Pilot, contract tests và một VNPAY backfill trên image hiện tại đã có, nhưng **5/11 acceptance criteria** vẫn chưa đủ evidence để đóng ở mức business acceptance. Các mục còn lại được phân biệt rõ giữa contract evidence, live smoke evidence và rollout rehearsal.

## Mục tiêu

Thay thế APScheduler bằng Apache Airflow ở lớp scheduling và workflow control-plane, đồng thời tái sử dụng fetcher, ingestion pipeline, checkpoint và recovery contract đã hoàn tất ở Sprint 2.

Sprint 2.5 không viết lại ingestion flow. Airflow chỉ quyết định khi nào một stream chạy, chạy theo dependency nào, retry ở cấp task ra sao và operator theo dõi workflow thế nào.

## Pilot đã triển khai (2026-08-09)

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
  sau khi VNPAY backfill hoàn tất trên range business-day của fixture.

### Hardening review/schedule hiện tại

- Review Step 3 mặc định chỉ hiển thị phần tổng quan; trace samples được mở
  theo yêu cầu để tránh modal bị dài và khó đọc.
- Packet sinh trong backfill luôn mang `backfillRunId`; packet pending được
  chọn theo đúng `reconciliationDate`, tránh nối nhầm packet của ngày khác.
- Schedules có action **Open pending review**, **Backfill date range** và
  **View runtime details** trong overflow menu. Polling dùng request sequence
  để response cũ không ghi đè state mới khi run chuyển sang `WAITING_REVIEW`.
- Runtime timeline phân biệt completed (xanh), waiting/processing (amber) và
  failed/blocked (đỏ); màu đỏ chỉ dùng cho lỗi.

### Post-refactor runtime hardening

Các thay đổi Phase 2 sau đây là một phần của runtime contract hiện tại:

- `run.py` khởi chạy trực tiếp `src.api:create_app`; root wrappers `api/` và
  `backend/` không còn được dùng.
- `src/core/utils.py` là nguồn canonical cho business-day bounds, date
  templates, SHA-256 file identity và runtime error formatting. Các module
  utility core cũ đã được xóa; code mới không phụ thuộc compatibility wrapper.
- API fetch unit giữ `metadata.sourceUnitKey` explicit làm identity canonical.
  Nếu raw stage đã hoàn tất, Run Now kết thúc an toàn với
  `SAFE_DUPLICATE`/`streamAlreadyCompleted` trước fetcher và review gate.
- Review packet visibility được xác định theo source scope (`rawStageKey`,
  `backfillRunId` hoặc source-file identity), không theo structure mapping đơn
  thuần. Vì vậy delivery mới cùng schema vẫn tạo được pending packet độc lập.
- Sau staged post-approval replay, checkpoint được chốt completed cùng
  high-water mark; không để runtime quay lại trạng thái chờ review cũ.
- Unique Mongo index `idx_fetch_unit_key_unique` chỉ áp dụng khi
  `fetchUnitKey` có kiểu string, nên document null/missing không va chạm.

Các file vận hành chính: `Dockerfile.airflow`, `requirements-airflow.txt`, `docker-compose.yml`, `dags/reconciliation_ingestion.py` và `docker/bootstrap-airflow-db.sh`.

### Evidence pilot live ViettelPay

Pilot manual-only đã chạy qua API ứng dụng với mock API ba trang:

- Run đầu (`f68207de-3f25-44f7-b357-7881a444b65a`) persist trang 1 rồi fail đúng trang 2 sau ba HTTP 504; checkpoint giữ trang 1 `COMPLETED`, PostgreSQL có 2/2 ingestion key distinct và quarantine bằng 0.
- Recovery retry (`e2d7b6d7-a6a7-43fc-ac8a-9d65bf11f4a7`) resume từ trang 2, xử lý hai unit còn lại và kết thúc `COMPLETED`; PostgreSQL có 6/6 ingestion key distinct.
- Replay (`616e2e4a-55b4-4397-900f-8aab1e0923f6`) trả `streamAlreadyCompleted=true`, xử lý 0 unit mới và giữ nguyên 6 dòng, 0 duplicate.
- API server, scheduler và DAG processor được restart; health trở lại `healthy` và run sau restart (`c6389099-f195-4d32-8517-6de4ca0da575`) hoàn tất qua Airflow.

Trạng thái local sau pilot: API dùng `APP_AUTOMATION_ORCHESTRATOR=airflow`,
`AIRFLOW_GLOBAL_SCHEDULE=none`, và không còn service/container APScheduler.
Nút Run Now/retry/backfill trên UI đi qua Airflow; cron tự động chưa được bật
cho các partner khác trong manual pilot.

### Khởi động local

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

### Contract path FileDrop/SFTP trong Airflow

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

### Contract submit và outcome

- API tạo `runtimeRunId`, dùng DAG run ID xác định `manual__<runtimeRunId>` và submit qua `/api/v2/dags/{dag_id}/dagRuns`.
- `409` hoặc POST timeout được probe lại bằng GET; chỉ coi là idempotent khi runtime/correlation khớp.
- `COMPLETED`, `NO_DATA`, `ALREADY_PROCESSED` và `WAITING_REVIEW` kết thúc task thành công. `WAITING_REVIEW` là operator gate: application runtime giữ trạng thái chờ duyệt và review packet là nguồn hành động tiếp theo, không phải Airflow task failure/retry.
- `FAILED` và `BLOCKED` làm task fail; deployment mặc định đặt
  `AIRFLOW_TASK_RETRIES=0`, nên không có native/automatic retry. Checkpoint
  tiếp tục là source of truth để resume. Manual retry trên UI đọc mapped task bằng `task_id/map_index` rồi
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

### Phân biệt lỗi Airflow và recovery page

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

### Demo manual retry ViettelPay có thể tái lập

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

### Raw staging bền vững cho API stream lớn

Đã bổ sung `raw_ingestion_page` cho API pagination:

- Payload đầy đủ nằm trong GridFS bucket `raw_ingestion`; Mongo document chỉ giữ metadata, hash, cursor, bounded `sampleRows`, trạng thái và thời hạn lưu.
- Application stream runner fetch hết các page và stage theo `sourceUnitKey` trước khi chạy ingestion. Review packet chỉ được tạo sau khi page cuối xác nhận `has_more=false`; nếu page giữa stream lỗi thì chỉ giữ raw/checkpoint để retry, chưa tạo packet. Khi thiếu mapping sau khi fetch hoàn tất, stream chuyển `WAITING_REVIEW`, không ghi `partner_transaction`, nhưng raw pages vẫn còn để tạo packet đầy đủ.
- Sau approval, post-approval runner materialize từng page từ GridFS, replay qua ingestion/reconciliation hiện có và đánh dấu page `CONSUMED`. Retry upload và replay theo `sourceUnitKey` là idempotent.
- Retention mặc định là 7 ngày; daily job dọn metadata và GridFS payload hết hạn. Nếu adapter không phải Motor (test double/legacy), hệ thống giữ fallback one-page gate cũ.

## Phần hợp nhất: recovery hardening

Phần này hợp nhất nội dung hardening trước đây của Sprint 2.6 vào Sprint 2.5.
Mục tiêu là bảo đảm một workflow owner rõ ràng, recovery có lịch sử đầy đủ và
không làm mất boundary của checkpoint khi Airflow retry hoặc operator replay.

### Bản đồ ưu tiên và trạng thái

| Ưu tiên | Vấn đề/acceptance | Evidence hiện tại | Trạng thái |
|---|---|---|---|
| P0 | Không để APScheduler và Airflow cùng trigger một stream | Compose pilot dùng Airflow; `AIRFLOW_GLOBAL_SCHEDULE=none`; không còn legacy scheduler | Đạt ở local pilot |
| P0 | Durable staging failure phải xuất hiện trong recovery timeline | Checkpoint event, runtime attempt và raw page giữ lại để retry | Đạt qua test/contract |
| P0 | Retry phải hiển thị cả attempt cũ và attempt mới | Recovery events hợp nhất theo `eventId`, UI hiển thị `FAILED → RETRY_REQUESTED → STARTED → COMPLETED` | Đạt; ViettelPay đã kiểm chứng live |
| P1 | Review scope phải đọc toàn bộ API stream, không chỉ page đầu | Raw-stream endpoint và mapping validation đọc bounded pages theo `rawStageKey` | Đạt qua test; live rerun mapping còn mở |
| P1 | Approved mapping phải replay toàn bộ stream như một logical batch | Một `rawStageKey`, một logical file, các page dùng chung `sourceFileId`, reconcile một lần | Đạt qua regression; live business rerun còn mở |
| P1 | Evidence nội bộ phải giữ đúng timezone business day | Mốc Asia/Ho_Chi_Minh được đổi sang UTC trước SQL; packet lưu count và preview giới hạn | Đạt qua test/live evidence |
| P1 | Lỗi chọn Airflow/config không để runtime treo ở QUEUED | Runtime chuyển `FAILED` với error code có thể hành động | Đạt qua test |
| P2 | Retry native của Airflow không hard-code attempt 1 | `AIRFLOW_TASK_RETRIES=0` trong manual pilot; retry do operator | Đạt ở pilot |
| P2 | Health Airflow live phải có evidence riêng | Healthcheck, DAG import error và process list đã ghi nhận | Local đạt; production rollout còn mở |

### Flow recovery sau hardening

```text
Operator/API
  → một orchestrator được chọn (Airflow hoặc adapter local)
  → runtime QUEUED + correlation
  → Airflow chọn stream / mapped run
  → fetch và raw staging bền vững
  → attempt event (start/progress/failure/success)
  → checkpoint + source-unit ingestion khi đủ điều kiện
  → review packet hoặc reconciliation
  → terminal runtime status, giữ lại lịch sử attempt
```

`WAITING_REVIEW` vẫn là business gate hợp lệ. Khi mapping thiếu/cũ hoặc stream
API đã stage đủ page, packet giữ cùng `rawStageKey`; approval replay toàn bộ
stream như một logical reconciliation file. Khi một page lỗi giữa stream,
partial canonical rows bị dọn, raw page và checkpoint vẫn replay được, còn
reconciliation chỉ chạy sau khi tất cả page hoàn tất.

### Evidence tự động và live hiện có

- Backend quality, Ruff, mypy, dependency check, Compose config, frontend
  lint/typecheck/build và Playwright smoke đã có trong evidence của pilot.
- Recovery contract bao phủ retry, blocked/resolve/skip, review gate, timezone,
  full-stream mapping, logical batch và backfill isolation.
- Live ViettelPay đã chứng minh page-2 failure → manual retry → 3/3 source
  units và 6/6 partner rows hoàn tất; current-image VNPAY FileDrop backfill
  ngày 2026-08-14 hoàn tất `1/1` ngày với `3 MATCHED` rows và giữ source file.
- Còn thiếu để đóng business acceptance: multi-fingerprint FileDrop và live
  SFTP recovery, đầy đủ retry/state matrix, scheduled chạy đồng thời với
  backfill, live mapping-gated review và rollback theo partner không reset dữ liệu.

### Nhật ký hardening được giữ lại trong tài liệu hợp nhất

- Chuẩn hóa business key vào field nghiệp vụ `partner_trace` theo mapping của
  từng partner; `vspTransId` chỉ là một source field của case ban đầu, không
  phải canonical name toàn nền tảng. Legacy fallback vẫn là
  `partner_metadata.vspTransId` → `partner_id`, đồng thời chuẩn hóa timestamp
  aware về UTC-naive trước khi ghi PostgreSQL; SQL status, ordering và
  migration index đã được kiểm chứng.
- Review Mapping đọc `GET /api/v1/review-packets/{packet_id}/raw-records`
  theo trang giới hạn, giữ `streamRowIndex`, `rowIndex`, `page` và
  `sourceUnitKey`; browser không tải toàn bộ payload một lần.
- Logical batch API giữ ba raw page dưới một `rawStageKey`, một
  `reconciliation_file`, các transaction dùng chung `sourceFileId` và chỉ
  reconcile một lần sau khi mọi page thành công. Failed-middle-page dọn rows
  tạm nhưng để raw page replay được.
- API pagination có durable staging sẽ luôn đi qua scope Review Packet, kể cả
  khi mapping đã approved. Hành động **Approve keep current** replay cùng
  batch sau approval; không còn đường bypass tạo một file cho mỗi page.
- Fixture `make viettelpay-sprint2-reset` cố ý không tạo approved mapping để
  tái hiện packet trên UI; fixture recovery approved mapping vẫn dùng để kiểm
  chứng retry/ingestion mà không tạo packet ngoài mapping gate.
- Internal evidence dùng business timezone khi query PostgreSQL và lưu
  `internalRecordCount` cùng `internalPreview` bounded; packet hiển thị ngày
  theo `Asia/Ho_Chi_Minh` thay vì UTC calendar date.
- JSON/JSONL/NDJSON mapping giữ `sourceField` theo key/header thực tế; mapping
  runtime bảo toàn dictionary rows, còn mapping column legacy vẫn dùng list rows.
- FileDrop/SFTP packet đọc source file theo pagination có giới hạn và xử lý
  mapping path `/opt/airflow/app` ↔ `/app`; recovery summary không lặp badge
  của runtime `RUNNING`/`WAITING_REVIEW`.
- Manual pilot đặt `AIRFLOW_TASK_RETRIES=0`. Operator retry gửi
  `reset_dag_runs=true` để DagRun terminal không chặn lần chạy lại; attempt
  history vẫn hiển thị cả retry cùng runtime và fallback runtime mới.
- Scope classification dựa trên business-key overlap, historical coverage,
  new-key ratio và changed payload; không suy luận từ token tên file.
  `INCREMENTAL_APPEND` chỉ reconcile batch hiện tại, `REPLACEMENT` xử lý file
  thay thế đầy đủ và `FULL_SNAPSHOT` mới thay toàn bộ partner/date slice.

## Baseline hiện tại

Repository hiện có các boundary phù hợp cho migration:

- [Application stream runner](../../src/application/automation/stream_runner.py) load config, gọi fetcher, xử lý pagination/file units và kết nối application orchestration.
- [Source-unit orchestrator](../../src/application/ingestion/source_unit_orchestrator.py) đã giữ checkpoint sequencing, claim, retry, completion và advance boundary.
- [Fetcher contract](../../src/fetchers/base.py) chuẩn hóa `FetchResult` và `SourceUnitMetadata` cho API, SFTP và FileDrop.
- [Sprint 2 recovery contract](sprint-2-incremental-recovery.md) yêu cầu xử lý tuần tự, checkpoint chỉ advance sau persistence thành công và backfill không làm thay đổi scheduled stream.

## Quyết định kiến trúc

### Quyết định

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

### Ranh giới trách nhiệm

| Component | Owns | Does not own |
|---|---|---|
| Airflow | DAG schedule, task dependency, task-level retry, timeout, pool, backfill trigger, task logs | `source_unit_key`, checkpoint boundary, ingestion idempotency, business rules |
| Application service | One stream execution, fetch/ingest sequencing, runtime result contract | Global workflow scheduling |
| Fetchers | API/SFTP/FileDrop retrieval and source-unit identity | Checkpoint advancement and downstream reconciliation |
| Checkpoint repository | Claim, completed/failed/blocked state, cursor and high-water mark | Airflow task state |
| Ingestion pipeline | File claim, mapping, validation, PostgreSQL persistence and ingestion outcome | DAG scheduling |

Airflow retry không thay thế retry policy của source unit. Hai lớp phải được giới hạn rõ để tránh retry storm: application retry xử lý lỗi fetch/persist của unit; Airflow retry xử lý task/process failure hoặc restart ở cấp workflow.

## Vì sao migrate sau Sprint 2

Sau Sprint 2, migration chủ yếu là thay adapter scheduling vì các contract khó nhất đã có:

- `FetchResult` và `SourceUnitMetadata` có identity ổn định.
- Checkpoint là source of truth cho resume/replay.
- `process_source_units()` giữ sequential boundary và không advance trước persistence.
- Replay an toàn dựa trên `fileHash`, `fetchUnitKey` và `ingestion_key`.
- Scheduled stream và backfill đã có identity riêng.

Airflow vẫn không tự fetch dữ liệu. DAG phải gọi application entrypoint để application gọi `APIFetcher`, `SFTPFetcher` hoặc `FileDropFetcher`.

## Thiết kế mục tiêu cho migration đầu tiên

### Hình dạng DAG

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

### Cấu hình và secrets

- `FetchConfig` vẫn là nguồn cấu hình nghiệp vụ của ứng dụng trong giai đoạn đầu.
- Airflow giữ schedule, pool và operational parameters; không copy toàn bộ partner config vào DAG source.
- Pilot nhận application credentials qua environment như stack hiện tại; partner credential không hard-code trong DAG và không ghi vào REST `conf`/XCom. Trước production cần chuyển secret distribution sang Docker/Kubernetes secrets hoặc Airflow secrets backend.
- Airflow metadata database nên là database/schema riêng với application PostgreSQL. Không dùng Airflow metadata tables làm persistence cho ingestion.

### Kiểm chứng local hiện tại — 2026-08-14

Compose pilot hiện tại được kiểm tra sau khi build lại image API:

- `reconciliation-api` chạy từ image
  `sha256:cb2c9e4197efd6c1b925f510b3cfe43d604f07814285d3811fa5a15887214d13`.
- API `/openapi.json` trả HTTP 200.
- Airflow metadata database, scheduler và DAG processor ở trạng thái healthy.
- `airflow dags list-import-errors` trả `No data found`.
- Airflow là owner hiện tại với `AIRFLOW_GLOBAL_SCHEDULE=none` và
  `AIRFLOW_TASK_RETRIES=0`.
- Compose không còn process legacy `reconciliation-scheduler`.

Mục evidence về local service health đã đạt. VNPAY FileDrop backfill trên image
hiện tại cho ngày `2026-08-14` cũng hoàn tất `1/1` ngày với `3 MATCHED` rows;
source file vẫn còn trong thư mục `mock_data` được mount. Đây là smoke evidence,
chưa phải acceptance đầy đủ cho multi-file/SFTP recovery.

### Ma trận evidence checklist — 2026-08-14

| Checklist | Current evidence | Status before business acceptance |
|---|---|---|
| FileDrop/SFTP ordering and source retention | `65` focused FileDrop/SFTP/ingestion tests pass; current-image VNPAY FileDrop source was retained. Multi-fingerprint recovery and a live SFTP run are still missing. | Partial |
| Bounded Airflow/application retry | `80` retry/checkpoint/automation/stream tests pass; deployment uses `AIRFLOW_TASK_RETRIES=0`. Full live timeout/exhaustion matrix is still missing. | Partial |
| `BLOCKED`, resolve/skip, `WAITING_REVIEW` | Contract and API tests cover the transitions; live ViettelPay recovery covers operator retry. A live terminal-blocked resolve/skip and mapping-gated review run are still missing. | Partial |
| Scheduled checkpoint isolation | Backfill completed on the current image and Mongo contains separate `SCHEDULED` and `BACKFILL` checkpoint records; the scheduled record retained `scheduled-baseline-unit`. The scheduled record was a seeded baseline, not a concurrent scheduled execution. | Partial |
| Per-partner rollback without reset | Runbook and pause/previous-artifact procedure exist, but no partner-scoped deployment rollback rehearsal was run. | Pending |

The five checkboxes below remain unchecked intentionally: the missing portions
are environment/rollout evidence, not a reason to weaken the acceptance bar.

### Scheduling ownership

Trong manual pilot, Airflow là owner duy nhất cho các stream được operator kích
hoạt. DAG giữ `AIRFLOW_GLOBAL_SCHEDULE=none`, do đó không có daily trigger tự
động và không có dual-run với scheduler khác.

## Các đầu việc migration

### Task 0 — Chốt ADR và inventory

- Ghi nhận Airflow là control-plane scheduler, không phải fetcher hay checkpoint store.
- Mapping lịch sử từ scheduler job/config/runtime status sang DAG/task/run
  metadata đã được hoàn tất trong pilot.
- Chốt Airflow major version, executor, deployment target, timezone và ownership vận hành.

**Verify:** ADR được review; không còn hai thành phần cùng sở hữu production schedule.

### Task 1 — Ổn định application entrypoint (đã triển khai)

- Tạo một entrypoint rõ ràng cho Airflow gọi: `run_source_stream()` trong application automation.
- Chuẩn hóa kết quả thành `success`, `outcome`, `errorCode`, `retryable`, checkpoint position và runtime run id.
- Bảo đảm entrypoint không phụ thuộc vào process của APScheduler.

**Verify:** gọi trực tiếp bằng CLI/test runner vẫn chạy được API pagination, FileDrop/SFTP, replay, retry và backfill isolation.

### Task 2 — Dựng Airflow development stack (đã triển khai cho local pilot)

- Thêm Airflow scheduler, API server/web UI, DAG processor/worker theo executor đã chọn và metadata PostgreSQL riêng.
- Thiết lập healthcheck, migration command, timezone, log retention và DAG deployment.
- Tạo Connections/secrets cho MongoDB, application PostgreSQL và partner endpoints theo nguyên tắc least privilege.

**Verify:** `airflow db check`, Airflow UI/API healthy, DAG parse không lỗi và application database không bị thay đổi schema ngoài migration đã duyệt.

### Task 3 — Viết pilot DAG (đã triển khai)

- Tạo DAG generic gọi application entrypoint cho một partner/config có fixture recovery, ưu tiên ViettelPay.
- Cấu hình schedule, `execution_timeout`, bounded Airflow retries và pool slot cho từng stream.
- Propagate Airflow `dag_run_id`/`task_instance` correlation vào `partner_runtime_run` và structured logs.

**Verify:** manual run và scheduled run tạo đúng một runtime run; page/file failure dừng đúng boundary; retry tiếp tục từ checkpoint và không tạo duplicate.

### Task 4 — Contract và recovery testing (ViettelPay live pilot đạt; matrix rộng hơn còn mở)

- Test DAG import/serialization và task parameter validation.
- Giữ regression của Sprint 1–2: failure giữa page, restart/resume, replay, duplicate invariant, FileDrop/SFTP retry và backfill isolation.
- Test Airflow retry khi process bị kill sau persistence nhưng trước task completion.
- Test timeout, missed schedule, concurrent trigger và pool saturation.

**Verify:** Airflow task retry không advance checkpoint sai, không tạo duplicate ingestion key và không chạy vượt blocked boundary.

### Task 5 — Dual-run và cutover theo partner (đã thay thế bằng manual pilot)

- Chạy Airflow pilot ở manual/shadow mode.
- So sánh runtime status, checkpoint, row counts, duplicate count, latency và error classification giữa scheduler cũ và pilot.
- Không triển khai dual-run trong manual pilot; Airflow được xác minh trên
  fixture/ViettelPay/VNPAY và giữ manual-only để giới hạn blast radius.

**Verify:** mỗi partner có một scheduler owner duy nhất; cutover/revert không làm mất checkpoint hoặc tạo double run.

### Task 6 — Gỡ APScheduler (đã hoàn tất cho manual pilot)

- Đã xóa registration/startup path, Compose service/profile, implementation,
  dependency và Mongo `apscheduler_jobs` control-plane dependency.
- Đã cập nhật Docker Compose, CLI, README, test suite và runbook.
- Runtime history cũ vẫn giữ nguyên trong Mongo để audit; không migrate sang
  Airflow metadata.

**Verify:** production stack không còn process APScheduler; Airflow là nguồn schedule duy nhất; manual run và operator recovery vẫn hoạt động.

### Task 7 — Kiểm chứng cuối (live pilot đạt; outage matrix còn mở)

- Chạy full backend quality/regression suite.
- Chạy deterministic Sprint 2 evaluation và pilot Airflow evaluation.
- Kiểm tra restart Airflow, restart worker, metadata DB outage, application DB outage và partner timeout.
- Đối chiếu invariant: không duplicate ingestion key, checkpoint contiguous, blocked unit không tự skip, backfill không advance scheduled checkpoint.

**Exit criterion:** manual pilot có evidence về manual run, retry, restart và
  ordered backfill; daily cron production là follow-up riêng.

## Cutover và rollback

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

## Tiêu chí acceptance

Tổng hợp hiện tại: **6/11 đạt**, **5/11 còn pending**. Các mục `[ ]` là điều kiện đóng Sprint 2.5, không chỉ là follow-up tùy chọn.

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

### Acceptance còn mở

| Mục | Bằng chứng cần bổ sung |
|---|---|
| FileDrop/SFTP ordering và source retention | Chạy recovery thực tế qua từng fingerprint, chứng minh source còn đủ lâu để resume |
| Bounded retry giữa Airflow và application | Matrix retry/timeout/error chứng minh không retry vô hạn hoặc retry chồng |
| `BLOCKED`, operator resolve/skip, `WAITING_REVIEW` | Contract/integration acceptance cho từng state transition và action |
| Scheduled checkpoint không bị backfill thay đổi | Chạy ordered backfill đồng thời với scheduled checkpoint và đối chiếu trước/sau |
| Rollback per partner không reset dữ liệu | Thực hiện rollback pilot theo partner, giữ nguyên checkpoint/runtime và audit evidence |

## Rủi ro và biện pháp giảm thiểu

| Risk | Mitigation |
|---|---|
| Airflow retry chồng với application retry | Phân loại trách nhiệm, đặt max attempts/backoff riêng và test failure matrix |
| Hai scheduler cùng trigger một stream | Dual-run chỉ manual/shadow; cutover theo partner; lock/claim vẫn là safety net |
| DAG trở thành nơi chứa business logic | DAG chỉ gọi application entrypoint; review import boundary |
| Airflow metadata và application DB bị trộn | Dùng metadata DB riêng, migration/backup riêng |
| XCom/log làm lộ credential hoặc raw payload | Connections/secrets backend; chỉ truyền identifiers/status nhỏ |
| Tách page thành task làm sai sequential recovery | Giai đoạn đầu giữ một task gọi sequential source-unit service |
| Airflow deployment trở thành bottleneck mới | Healthcheck, pool limit, worker restart test và operational runbook |

## Tài liệu tham chiếu

- [Apache Airflow overview and distributed architecture](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html)
- [Airflow scheduler](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/scheduler.html)
- [Airflow production deployment](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/production-deployment.html)
- [Airflow pools and task concurrency](https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html)
- [Repository application boundaries](../../README.md#architectural-boundaries)
- [Sprint 2 incremental processing and recovery](sprint-2-incremental-recovery.md)
