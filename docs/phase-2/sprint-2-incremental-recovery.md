# Plan 2 — Incremental Processing và Recovery

## 1. Mục tiêu và kết quả bắt buộc

Xây dựng cơ chế xử lý dữ liệu theo từng source unit/page/file, lưu tiến độ sau khi persistence thành công và retry an toàn sau lỗi hoặc restart.

Sprint này phải cho phép dùng ViettelPay làm partner demo API với pagination/cursor, lỗi giữa chừng và resume từ checkpoint mà không bỏ sót hoặc tạo duplicate.

Kết quả cuối cùng:

- API fetcher xử lý được nhiều page theo `cursor` hoặc `next_page_token`.
- Checkpoint xác định chính xác unit cuối cùng đã persist thành công.
- Lỗi trước checkpoint không làm tiến độ nhảy qua unit chưa hoàn tất.
- Restart tiếp tục từ unit chưa hoàn tất hoặc replay boundary an toàn nhờ contract Sprint 1.
- Retry có giới hạn và phân biệt lỗi tạm thời với lỗi terminal; không retry vô hạn hoặc tự ý bỏ qua unit.
- FileDrop/SFTP có cùng semantics ở cấp file/fingerprint, nhưng không bị ép dùng cursor API.
- Backfill độc lập với scheduled stream và không thay đổi checkpoint scheduled.

## 2. Hiện trạng đã được xác nhận

Sprint 1 đã cung cấp các ranh giới phải được tái sử dụng:

- `fileHash` bảo vệ replay file.
- `fetchUnitKey` bảo vệ replay page/fetch unit.
- `(identify, ingestion_key)` là unique contract trên PostgreSQL.
- `IngestionPipeline.process_file()` nhận `fetch_unit_metadata`.
- `scheduler.jobs._fetch_unit_metadata()` đã truyền endpoint/page/cursor/window context.
- Duplicate là outcome hợp lệ, không phải fatal error.

Khoảng trống hiện tại:

- `APIFetcher` chỉ gọi một HTTP response và ghi một file.
- Chưa có model/repository checkpoint và source-unit state.
- FileDrop/SFTP mới chọn một file, chưa quản lý nhiều candidate/fingerprint/retry.
- `ReconciliationFile` chưa gắn lifecycle với source unit/checkpoint một cách atomic.
- Chưa có test chứng minh crash giữa page, retry sau restart và backfill isolation.

## 3. Phạm vi và ranh giới không được vượt qua

### Trong phạm vi

- Checkpoint model, repository và Mongo indexes.
- API pagination/cursor, raw response per page và stable source identity.
- FileDrop/SFTP discovery, fingerprint và retry theo file boundary.
- Scheduler orchestration cho load/retry/advance checkpoint.
- Pipeline source-unit context, status transition và recovery boundary.
- Integration/evaluation tests và demo seed ViettelPay.
- Sequential stream orchestration: một active worker cho mỗi stream; chỉ giữ
  parallelism ở batch write nội bộ đã có trong pipeline.

### Ngoài phạm vi

- Không sửa thuật toán hoặc schema matching trong `src/reconciliation/`.
- Không sửa frontend hoặc thêm màn hình Sprint 2.
- Không sửa AI, insights, copilot hoặc prompt/provider.
- Không đổi business meaning của transaction.
- Không dùng checkpoint để thay thế `fileHash`, `fetchUnitKey` hoặc `ingestion_key`.
- Không resume Excel/CSV bằng byte offset; chỉ resume ở page/file/batch boundary.
- Không thêm parallel fetch giữa partner, giữa file, hoặc giữa các cursor page
  trong Sprint 2; throughput chỉ được tối ưu ở batch write nội bộ nếu benchmark
  chứng minh cần thiết.

## 4. Thuật ngữ và identity contract

| Khái niệm | Định nghĩa bắt buộc |
|---|---|
| `stream_key` | Identity ổn định của một luồng scheduled/backfill: partner + fetch config + source type + logical stream. |
| `source_unit` | Đơn vị có thể retry độc lập: API page/cursor hoặc một file remote/local. |
| `source_unit_key` | Fingerprint ổn định của endpoint + page/cursor/window/file identity + config version. |
| `checkpoint` | Trạng thái tiến độ của stream, chỉ phản ánh unit đã persist thành công. |
| `cursor` | Token do API trả về để lấy unit kế tiếp; không tự suy diễn nếu API có token. |
| `high_water_mark` | Fallback cho API không có cursor, phải có overlap window và transaction idempotency. |
| `backfill` | Execution mode có range/stream riêng, không advance checkpoint scheduled. |

`fetchUnitKey` của Sprint 1 vẫn là lớp duplicate claim. Checkpoint chỉ quyết định unit nào cần fetch/retry tiếp theo; không được coi checkpoint là bằng chứng persistence thành công nếu source-unit claim chưa completed.

### Sequential execution policy

- Mỗi `(partner, fetch_config, source_type, stream_key, mode)` chỉ có một
  active orchestration worker.
- Daily scheduler xử lý các partner/config theo thứ tự; không dùng
  `asyncio.gather()` để chạy nhiều stream trong Sprint 2.
- API cursor được fetch và persist từng page: chỉ request page kế tiếp sau khi
  page hiện tại đã persist và checkpoint đã completed. Không prefetch toàn bộ
  stream trước khi ingest.
- FileDrop/SFTP discover theo thứ tự deterministic và xử lý từng fingerprint một.
- `write_workers` hiện có chỉ áp dụng cho các batch ghi bên trong một file/page;
  không biến thành source-unit hoặc partner-level parallelism.
- Concurrent claim vẫn được test để bảo vệ race/replay, nhưng không phải mode
  throughput mặc định của hệ thống.

## 5. State machine và transaction boundary

### Checkpoint state

```text
ABSENT
  -> DISCOVERED
  -> PROCESSING
  -> COMPLETED   (chỉ sau ingestion/persistence thành công)
  -> FAILED      (có error và attempt metadata)
  -> PROCESSING  (retryable và đã đến thời điểm retry)
  -> BLOCKED     (terminal error hoặc exhausted attempts)
  -> DISCOVERED  (chỉ sau operator resolve/skip có audit)
```

Checkpoint phải lưu tối thiểu:

- `partner`, `fetch_config_id`, `source_type`, `stream_key`.
- `mode`: `SCHEDULED` hoặc `BACKFILL`.
- `current_unit_key`, `last_completed_unit_key`.
- `cursor_before`, `cursor_after` hoặc high-water mark.
- `status`, `attempt_count`, `last_error`, `error_code`, `retryable`.
- `next_retry_at` và `blocked_at`/`blocked_reason` khi retry không còn hợp lệ.
- `started_at`, `completed_at`, `updated_at`.
- `config_version` và source endpoint/stream metadata.

Trong execution mode tuần tự, `last_completed_unit_key` là contiguous boundary
của stream: không claim unit sau khi unit trước chưa completed. Không cần lưu
out-of-order completion set hoặc thêm source-unit ledger cho đến khi hệ thống
có yêu cầu xử lý nhiều unit đồng thời trong cùng stream.

### Atomicity rules

1. Claim hoặc tạo source unit trước khi ingest.
2. Persist partner transactions qua pipeline conflict-safe.
3. Chỉ khi pipeline kết thúc ở trạng thái completed/accepted thì source unit mới được đánh dấu completed.
4. Chỉ sau bước 3 mới advance checkpoint.
5. Nếu bất kỳ bước nào sau claim thất bại, checkpoint giữ nguyên giá trị trước unit đó.
6. Retry unit completed phải trả duplicate/replay outcome và không advance sai checkpoint.
7. Không archive/delete raw source trước khi unit và checkpoint đã được ghi thành công.
8. Không tự động skip unit terminal; chỉ operator action có audit mới được mở khóa hoặc bỏ qua boundary.

Nếu không thể thực hiện transaction xuyên Mongo và PostgreSQL, phải dùng trạng thái pending/retry có thể phục hồi; không giả vờ atomic bằng cách update checkpoint trước persistence.

## 6. Thiết kế theo source type

### API — ưu tiên chính của Sprint 2

- Hỗ trợ `GET`/`POST` theo `APIConfig` hiện có.
- Cho phép cấu hình pagination: page parameter, cursor parameter, response item path, next cursor path, page size.
- Không hard-code field JSON của ViettelPay vào fetcher.
- Mỗi page ghi raw response riêng, có content hash và `source_unit_key`.
- Response cuối phải biểu diễn rõ `items`, `has_more`, `next_cursor`, `source identity`.
- HTTP timeout/network/5xx retry theo attempt policy; lỗi parse/schema không được tự động advance.
- Không có next cursor thì kết thúc stream; cursor rỗng phải được phân biệt với cursor hợp lệ.

### FileDrop

- Discover tất cả candidate phù hợp pattern theo thứ tự deterministic; xử lý
  tuần tự từng candidate, dù một ngày thường chỉ có một file.
- Fingerprint gồm path/filename, size, modified time và content hash khi cần.
- Bỏ qua fingerprint đã completed.
- Retry fingerprint failed/incomplete.
- Không chọn “first file” theo thứ tự filesystem không xác định và không chạy
  nhiều fingerprint cùng lúc trong cùng stream.

### SFTP

- Stable remote identity gồm remote path, size, modified time và content hash sau download nếu cần.
- Chỉ đánh dấu completed sau khi download và ingestion thành công.
- Giữ remote/local source đủ lâu cho recovery theo retention policy.
- Với wildcard/multi-file remote path, discover deterministic và download/ingest
  từng remote object tuần tự.

## 7. Execution plan cho agent

### Thứ tự thực hiện sau Task 4

- Task 5 giữ phạm vi nhỏ: deterministic discovery và fingerprint tuần tự cho
  FileDrop/SFTP, không thêm worker pool.
- Task 6 là control-plane task tiếp theo: định nghĩa retryable/terminal,
  bounded retry, BLOCKED và operator resolve/skip trước khi scheduler có thể
  tự động retry.
- Task 7 là critical path sau đó: nối scheduler với checkpoint theo từng source
  unit cho cả API và file methods.
- Task 8 chỉ bắt đầu sau khi Task 5–7 chứng minh được restart/resume tuần tự;
  Task 9 luôn là bước cuối.
- Nếu cần tách implementation nhỏ hơn, thứ tự là: source identity → retry
  policy/state → API next-unit/resume loop → common checkpoint transition →
  FileDrop/SFTP adapter → backfill isolation.

### Task 1 — Chốt contract và compatibility

- Kiểm kê `FetchResult`, `ReconciliationFile`, `_derive_fetch_unit_key()` và scheduler call chain.
- Viết test contract cho metadata cũ không có checkpoint.
- Không đổi public behavior của Sprint 1 khi `fetch_unit_metadata` không có pagination.

**Verify:** test hiện tại của fetcher, pipeline và Sprint 1 vẫn pass; API one-shot hiện tại vẫn tạo đúng một unit.

### Task 2 — Checkpoint model/repository/index

- Tạo `src/models/ingestion_checkpoint.py`.
- Tạo unique key cho `(partner, fetch_config_id, source_type, stream_key, mode)`.
- Thêm index cho pending/failed units và updated time.
- Định nghĩa create-or-get, claim, mark-failed, mark-completed và advance methods.

**Verify:** concurrent claim chỉ có một winner; completed checkpoint không bị lùi; failed checkpoint có thể retry.

### Task 3 — Source-unit metadata và lifecycle

- Mở rộng `FetchResult` bằng source identity, units, cursor/high-water mark và retry metadata.
- Bổ sung source-unit reference/status vào `ReconciliationFile` hoặc metadata model phù hợp.
- Giữ alias/serialization tương thích với camelCase hiện tại.

**Verify:** mọi unit có key ổn định; thiếu identity bắt buộc bị reject, không sinh UUID ngẫu nhiên.

### Task 4 — API pagination/cursor

- Implement pagination trong `APIFetcher` bằng config-driven extraction.
- Ghi raw response theo unit, không ghi đè page trước.
- Phân biệt HTTP retry, parse failure, empty final page và invalid cursor.
- Bảo đảm page replay tạo cùng `source_unit_key`.

**Verify:** mock API 3 page trả về 3 unit theo đúng thứ tự, raw artifact và
`source_unit_key` ổn định; parse/HTTP failure dừng stream ở unit lỗi. Việc
persist từng unit, giữ checkpoint ở page trước và retry page lỗi được verify
end-to-end ở Task 7.

### Task 5 — FileDrop/SFTP recovery

- Chuyển discovery sang deterministic multi-file flow nhưng giữ một unit
  active tại một thời điểm.
- Thêm fingerprint và trạng thái retry.
- Không archive/delete trước completed checkpoint.
- Tái sử dụng `IngestionCheckpoint` chung; không tạo model checkpoint riêng cho
  FileDrop và SFTP.

**Verify:** file A completed bị skip; file B failed được retry theo thứ tự;
restart không bỏ qua file chưa completed; không có hai file cùng stream được
ingest đồng thời.

### Task 6 — Retry policy và terminal source-unit state

- Định nghĩa error classifier dùng chung cho fetch/persist: retryable
  (`timeout`, network, `429`, `5xx`, stale claim) và terminal (credential/config,
  schema/parse, malformed source, lỗi không thể sửa bằng retry).
- Bổ sung bounded retry: `max_attempts`/backoff policy, `next_retry_at` và
  không claim lại unit khi chưa đến thời điểm retry.
- Bổ sung trạng thái `BLOCKED` hoặc tương đương cho terminal/exhausted unit;
  giữ `error_code`, `retryable`, `blocked_reason` và attempt history đủ để
  vận hành quyết định.
- Định nghĩa operator action có audit: resolve/retry lại sau khi sửa nguyên
  nhân, hoặc skip/quarantine boundary có lý do bắt buộc. Không tự động skip.
- Giữ `IngestionCheckpoint` là stream boundary và gắn attempt/error chi tiết
  với source unit hiện tại; không tạo retry-policy model riêng theo source type.

**Verify:** retryable error được retry theo backoff và dừng ở `max_attempts`;
terminal error chuyển `BLOCKED` và không retry vô hạn; unit sau không được chạy
khi boundary đang blocked; operator resolve/skip có audit và chỉ khi đó mới
được advance; persistence thành công nhưng checkpoint update lỗi vẫn replay an
toàn nhờ contract Sprint 1.

### Task 7 — Scheduler orchestration

- Load checkpoint theo scheduled stream.
- Retry pending/failed unit trước khi fetch unit mới.
- Với API, fetch một page theo cursor hiện tại, gọi `_run_ingestion()` cho
  đúng page đó, rồi chỉ advance checkpoint sau khi persistence thành công;
  không tiêu thụ `fetch_result.units` theo kiểu prefetch toàn bộ rồi ingest sau.
- Với FileDrop/SFTP, fetch và ingest đúng một fingerprint, sau đó mới discover
  candidate kế tiếp.
- Dừng stream ngay tại unit lỗi; unit sau không được claim trước.
- Hỗ trợ explicit `mode=BACKFILL` và range/stream riêng.
- Truyền source/checkpoint context vào runtime run và pipeline.
- Giữ scheduler stream-level concurrency bằng một worker; không thêm worker
  pool cho partner/source unit trong task này.

**Verify:** scheduler restart tiếp tục đúng unit; page/file trước đó đã
completed không bị ingest lại ngoài replay-safe claim; backfill không thay đổi
scheduled checkpoint; duplicate outcome không làm scheduler failed nếu unit đã
persist hợp lệ; các batch write nội bộ vẫn dùng cấu hình hiện có.

**Implementation status (2026-08-04):** đã nối `run_fetch_config_once()` vào
checkpoint orchestration tuần tự. API pagination chạy one-page-per-iteration;
FileDrop/SFTP units được ingest theo thứ tự; claim/complete/advance dừng tại
unit lỗi; retry policy được áp dụng cho lỗi retryable; `BLOCKED` và operator
`SKIP` được tôn trọng; `mode=BACKFILL` được truyền qua stream/checkpoint
identity để cô lập với scheduled stream. Evidence: scheduler integration,
orchestrator và pagination tests pass trong regression suite.

### Task 8 — ViettelPay demo và evaluation suite

- Tạo mock API contract fixture có cursor, 3 page, duplicate boundary và lỗi có thể điều khiển.
- Tạo seed/reset riêng chỉ sau khi core checkpoint contract hoàn tất.
- Demo tuần tự phải thể hiện: initial run, failure giữa page, restart, resume,
  replay và final invariant.
- Không thêm demo command trước khi API pagination/checkpoint test pass.

**Verify:** một command reset chuẩn bị partner/config/data; UI Run now có thể khởi chạy; runtime hiển thị unit/checkpoint/outcome đủ để đánh giá.

**Implementation status (2026-08-04):** đã thêm ViettelPay mock contract 3 page
với cursor và controlled failure, lệnh reset fixture, lệnh evaluation và
markdown evidence report. Evaluation deterministic chạy đủ failure giữa page 2,
restart/resume, replay và duplicate-ingestion invariant: `4/4 passed`. Đây là
mock evidence, không ghi vào MongoDB/PostgreSQL production; real database
benchmark được giữ cho Task 9.

### Task 9 — Verification cuối cùng

- Chạy unit, integration và real Mongo/PostgreSQL benchmark.
- Chạy migration/index verification trên database test.
- Kiểm tra không có thay đổi ngoài scope.
- Cập nhật report bằng actual evidence, không ghi PASS nếu chỉ chạy mock.

## 8. Evaluation scenario catalog

| ID | Scenario | Expected invariant |
|---|---|---|
| S2-00 | Schema/index contract | Checkpoint unique stream key và query indexes tồn tại. |
| S2-01 | API 3-page happy path | 3 unit được persist tuần tự, cursor cuối được lưu, mọi row persist đúng một lần. |
| S2-02 | Failure giữa page 2 | Page 1 completed; checkpoint không vượt page 1; page 2 có error/attempt. |
| S2-03 | Restart recovery | Run mới retry page 2, không fetch/insert page 3 trước page 2; page 1 chỉ replay-safe nếu bị gọi lại. |
| S2-04 | Failure sau persistence trước advance | Retry không tạo transaction duplicate; checkpoint cuối cùng được advance đúng. |
| S2-05 | Cursor replay | Cùng cursor/page trả `FETCH_UNIT_REPLAY`, không tạo file/unit mới. |
| S2-06 | Invalid/missing cursor | Không advance; error code rõ ràng; không tạo cursor giả. |
| S2-07 | API final empty page | Stream hoàn tất đúng, không tạo phantom unit. |
| S2-08 | FileDrop multi-file | Candidate được sort deterministic; completed fingerprint bị skip; failed file được retry tuần tự. |
| S2-09 | SFTP stable identity | Cùng remote object không tạo hai source unit. |
| S2-10 | Scheduled vs backfill | Backfill không đọc/ghi scheduled checkpoint. |
| S2-11 | Claim race safety | Nếu hai worker cùng vô tình claim một unit, chỉ một owner thắng; đây là safety test, không phải throughput mode. |
| S2-12 | Config version change | Stream mới hoặc migration policy rõ ràng; không trộn checkpoint khác contract. |
| S2-13 | Data invariant | Không duplicate `(identify, ingestion_key)` sau mọi retry/restart scenario. |
| S2-14 | Retryable failure policy | Timeout/5xx/429 retry theo backoff; chưa đến `next_retry_at` thì không claim lại. |
| S2-15 | Terminal failure policy | Schema/config/malformed error hoặc exhausted attempts chuyển `BLOCKED`, không retry vô hạn và không advance. |
| S2-16 | Operator resolve/skip | Chỉ action có audit mới mở lại hoặc skip boundary; skip có reason và không tạo phantom completion. |
| S2-17 | Ordered catch-up | Ngày 1 completed, ngày 2/3 failed, ngày 4 pending: retry tuần tự từ ngày 2; ngày sau không chạy trước boundary. |

Mỗi scenario phải ghi `expected`, `actual`, `passed`, duration, checkpoint before/after, unit key và error/outcome vào report tương tự Sprint 1 benchmark.

## 9. Error and observability contract

Các error/outcome tối thiểu:

- `source_unit_claim_conflict`
- `fetch_timeout`, `fetch_network_error`, `fetch_http_error`
- `pagination_parse_error`, `invalid_cursor`
- `source_persist_error`, `checkpoint_advance_error`
- `file_duplicate`, `fetch_unit_replay`, `transaction_duplicate`
- `checkpoint_stale`, `backfill_checkpoint_isolated`
- `retry_not_due`, `retry_exhausted`, `source_unit_blocked`
- `source_unit_resolved`, `source_unit_skip_requires_approval`

Runtime/log metadata phải có `partner`, `stream_key`, `source_unit_key`, `cursor_before`, `cursor_after`, `attempt`, `checkpoint_before`, `checkpoint_after`, `file_id` và `outcome` khi có giá trị.

## 10. Agent guardrails

- Không triển khai ViettelPay-specific parsing trong generic `APIFetcher`; dùng config-driven paths.
- Không thêm checkpoint vào reconciliation engine.
- Không advance checkpoint trong fetcher; fetcher chỉ trả metadata/result. Scheduler/pipeline orchestration quyết định sau persistence.
- Không prefetch hoặc ingest song song các page/file trong cùng stream; cursor tiếp theo chỉ được lấy sau khi unit hiện tại completed.
- Không retry terminal error vô hạn và không tự động skip boundary khi vượt quá `max_attempts`.
- Không dùng read-before-write làm ranh giới duplicate duy nhất; vẫn dựa vào Mongo unique claim và PostgreSQL constraint của Sprint 1.
- Không xóa source khi status chưa completed.
- Không coi HTTP 200 là ingestion thành công.
- Không đánh dấu completed khi chỉ download xong nhưng persistence chưa xong.
- Không gộp scheduled và backfill vào cùng stream key.
- Mọi thay đổi schema phải có migration/index test và cleanup strategy cho test.
- Nếu test integration cần Mongo/PostgreSQL mà service unavailable, ghi `SKIP` rõ ràng; không đổi thành PASS giả.

## 11. Definition of Done

- [ ] API pagination/cursor và checkpoint chạy được qua toàn bộ scenario S2-00 đến S2-07.
- [ ] FileDrop/SFTP recovery đạt S2-08 đến S2-09 hoặc được ghi rõ là deferred với lý do.
- [ ] Backfill isolation đạt S2-10.
- [ ] Concurrent claim/config version/data invariant đạt S2-11 đến S2-13.
- [ ] Retryable/terminal classification, bounded backoff, `BLOCKED` và
  operator resolve/skip đạt S2-14 đến S2-17.
- [ ] Stream orchestration tuần tự: mỗi stream chỉ có một active unit; parallelism chỉ còn ở batch write nội bộ đã benchmark.
- [ ] Retry/restart không bỏ sót source unit và không tạo duplicate transaction.
- [ ] Checkpoint chỉ advance sau persistence thành công.
- [ ] Migration/index/schema có test và evidence trên database test.
- [ ] Sprint 1 test suite và benchmark vẫn pass.
- [ ] Không thay đổi reconciliation, frontend hoặc AI.
- [ ] Report cập nhật bằng số liệu chạy thực tế và có lệnh reproduce.
