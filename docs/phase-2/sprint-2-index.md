# Sprint 2 — Core Function Index

> Index các hàm core của Sprint 2 và Sprint 2.5 hợp nhất: source stream,
> checkpoint, retry/recovery, raw staging, review gate, Airflow và backfill.

## 1. Entry point và orchestration

| Hàm | Vị trí | Trách nhiệm chính | Handoff |
|---|---|---|---|
| `execute_stream` | [`service.py:24`](../../src/application/automation/service.py#L24) | Chuẩn hóa command, ngày nghiệp vụ, checkpoint và kết quả runtime cho một stream | `run_source_stream` |
| `run_source_stream` | [`stream_runner.py:61`](../../src/application/automation/stream_runner.py#L61) | Khởi tạo lifecycle, identity, checkpoint, fetcher, retry policy và chọn runner theo loại nguồn | `run_paginated_stream` hoặc `run_file_stream` |
| `select_stream_runner` | [`stream_runner.py:53`](../../src/application/automation/stream_runner.py#L53) | Chọn runner API pagination hoặc file/SFTP/FileDrop | Runner chuyên biệt |
| `process_source_units` | [`source_unit_orchestrator.py:12`](../../src/application/ingestion/source_unit_orchestrator.py#L12) | Xử lý source unit tuần tự, claim, ingest, retry, checkpoint và terminal outcome | `checkpoint_repository`, ingestion pipeline |
| `StreamLifecycle.start` | [`stream_lifecycle.py:94`](../../src/application/automation/stream_lifecycle.py#L94) | Tạo hoặc nối runtime run và ghi sự kiện bắt đầu | Runtime history |
| `StreamLifecycle.finish` | [`stream_lifecycle.py:143`](../../src/application/automation/stream_lifecycle.py#L143) | Chuẩn hóa outcome, stats và trạng thái kết thúc | API/Airflow result |

## 2. Identity, fetch và source unit

| Hàm | Vị trí | Core behavior | Kết quả |
|---|---|---|---|
| `stream_identity` | [`stream_identity.py:42`](../../src/application/automation/stream_identity.py#L42) | Tạo identity ổn định từ partner, config, source type, version, ngày và mode | `streamKey`, `sourceUnitKey` context |
| `source_stream_key` | [`stream_identity.py:23`](../../src/application/automation/stream_identity.py#L23) | Tách identity của stream khỏi từng page/file | Scheduled và backfill không dùng chung stream |
| `raw_stage_key` | [`stream_identity.py:29`](../../src/application/automation/stream_identity.py#L29) | Tạo khóa raw staging cho toàn bộ API stream trong một ngày | Các page cùng một `rawStageKey` |
| `units_after_checkpoint` | [`stream_identity.py:69`](../../src/application/automation/stream_identity.py#L69) | Lọc source unit đã hoàn tất để bảo đảm replay không xử lý trùng | Unit mới hoặc replay có chủ đích |
| `APIFetcher.fetch` | [`api_fetcher.py:32`](../../src/fetchers/api_fetcher.py#L32) | Gọi HTTP, đọc pagination/cursor và tạo metadata cho từng page | `FetchResult` |
| `BaseFetcher.build_file_source_unit` | [`base.py:166`](../../src/fetchers/base.py#L166) | Tạo source unit canonical cho file đã tải | `SourceUnitMetadata` |
| `FileDropFetcher.fetch` | [`filedrop_fetcher.py:27`](../../src/fetchers/filedrop_fetcher.py#L27) | Quét file, kiểm tra file sẵn sàng và trả các unit theo thứ tự | FileDrop units |
| `SFTPFetcher.fetch` | [`sftp_fetcher.py:26`](../../src/fetchers/sftp_fetcher.py#L26) | Tải file từ SFTP, chuẩn hóa path/metadata và trả source units | SFTP units |

## 3. Checkpoint và retry/recovery

| Hàm | Vị trí | Trách nhiệm |
|---|---|---|
| `RetryPolicy.classify` | [`retry_policy.py:45`](../../src/domain/ingestion/retry_policy.py#L45) | Phân loại lỗi thành retryable, blocked hoặc terminal |
| `RetryPolicy.can_retry` | [`retry_policy.py:51`](../../src/domain/ingestion/retry_policy.py#L51) | Áp dụng giới hạn attempt của application |
| `RetryPolicy.next_retry_at` | [`retry_policy.py:58`](../../src/domain/ingestion/retry_policy.py#L58) | Tính thời điểm retry theo backoff đã cấu hình |
| `IngestionCheckpointRepository.find_by_stream` | [`checkpoint_repository.py:126`](../../src/infrastructure/ingestion/checkpoint_repository.py#L126) | Đọc checkpoint theo stream identity và mode | Scheduled/backfill checkpoint |
| `IngestionCheckpointRepository.create_or_get` | [`checkpoint_repository.py:214`](../../src/infrastructure/ingestion/checkpoint_repository.py#L214) | Tạo checkpoint idempotent, xử lý race | Checkpoint hiện hành |
| `IngestionCheckpointRepository.claim_unit` | [`checkpoint_repository.py:227`](../../src/infrastructure/ingestion/checkpoint_repository.py#L227) | Claim source unit theo thứ tự và kiểm tra stale claim | `PROCESSING` hoặc replay result |
| `IngestionCheckpointRepository.mark_failed` | [`checkpoint_repository.py:356`](../../src/infrastructure/ingestion/checkpoint_repository.py#L356) | Lưu lỗi, attempt, retryability và cursor bị lỗi | `FAILED`/`BLOCKED` |
| `IngestionCheckpointRepository.release_for_review` | [`checkpoint_repository.py:401`](../../src/infrastructure/ingestion/checkpoint_repository.py#L401) | Dừng tại review gate nhưng giữ raw/checkpoint để resume | `WAITING_REVIEW` |
| `IngestionCheckpointRepository.resolve_blocked` | [`checkpoint_repository.py:462`](../../src/infrastructure/ingestion/checkpoint_repository.py#L462) | Ghi nhận operator resolve/skip với audit metadata | Tiếp tục hoặc bỏ qua unit |
| `IngestionCheckpointRepository.mark_completed` | [`checkpoint_repository.py:508`](../../src/infrastructure/ingestion/checkpoint_repository.py#L508) | Chốt persistence thành công cho unit | Completed unit timeline |
| `IngestionCheckpointRepository.advance` | [`checkpoint_repository.py:554`](../../src/infrastructure/ingestion/checkpoint_repository.py#L554) | Chỉ tiến checkpoint sau khi persistence hoàn tất | Contiguous checkpoint |
| `IngestionCheckpointRepository.prepare_manual_retry` | [`checkpoint_repository.py:154`](../../src/infrastructure/ingestion/checkpoint_repository.py#L154) | Chuẩn bị retry do operator yêu cầu và giữ attempt history | Retry cùng workflow |

## 4. API pagination, raw staging và review gate

| Hàm | Vị trí | Trách nhiệm | Handoff |
|---|---|---|---|
| `run_paginated_stream` | [`paginated_stream_runner.py:20`](../../src/application/automation/paginated_stream_runner.py#L20) | Fetch hết page, stage bền vững, dừng đúng lỗi giữa stream và mở review gate khi cần | Raw page hoặc ingestion |
| `run_file_stream` | [`file_stream_runner.py:14`](../../src/application/automation/file_stream_runner.py#L14) | Fetch file units, lọc theo checkpoint và đưa vào orchestrator | `process_source_units` |
| `stage_stream_unit` | [`stream_staging.py:6`](../../src/application/automation/stream_staging.py#L6) | Ghi raw page vào GridFS/metadata theo `sourceUnitKey` | Raw replay |
| `evaluate_stream_mapping` | [`stream_review_gate.py:11`](../../src/application/automation/stream_review_gate.py#L11) | Đánh giá mapping/config health trước ingestion | Mapping decision |
| `create_stream_review_packet` | [`stream_review_gate.py:16`](../../src/application/automation/stream_review_gate.py#L16) | Tạo packet scope cho stream đã stage đủ page | Guided Review |
| `create_stream_scope_review_packet` | [`proposal_creation.py:239`](../../src/application/review/proposal_creation.py#L239) | Persist review packet, mapping action và bounded evidence | `WAITING_REVIEW` |
| `run_ingestion` | [`stream_ingestion.py:245`](../../src/application/automation/stream_ingestion.py#L245) | Gọi ingestion pipeline cho một source file/page sau khi qua gate | Ingestion/reconciliation |

## 5. Airflow và operator backfill

| Hàm | Vị trí | Trách nhiệm |
|---|---|---|
| `select_stream_commands` | [`airflow_runtime.py:35`](../../src/application/automation/airflow_runtime.py#L35) | Chọn command cho scheduled/manual stream và giữ identifier-only payload | DAG input |
| `airflow_dag_run_id` | [`airflow.py:17`](../../src/infrastructure/workflows/airflow.py#L17) | Map runtime run sang DAG run id ổn định | Correlation |
| `AirflowWorkflowGateway.trigger` | [`airflow.py:41`](../../src/infrastructure/workflows/airflow.py#L41) | Submit DAG run qua Airflow REST API | Workflow submission |
| `AirflowWorkflowGateway.task_state` | [`airflow.py:47`](../../src/infrastructure/workflows/airflow.py#L47) | Đọc trạng thái task/mapped task | Recovery UI/API |
| `AirflowWorkflowGateway.retry_task` | [`airflow.py:85`](../../src/infrastructure/workflows/airflow.py#L85) | Clear/retry task và reset DagRun terminal khi cần | Operator retry |
| `expand_business_dates` | [`backfill_service.py:44`](../../src/application/automation/backfill_service.py#L44) | Mở rộng khoảng ngày inclusive theo timezone nghiệp vụ | Ordered backfill |
| `BackfillRunService.start` | [`backfill_service.py:84`](../../src/application/automation/backfill_service.py#L84) | Tạo parent run, persist ngày và submit Airflow backfill | `backfillRunId` |
| `BackfillRunService.resume_after_approval` | [`backfill_service.py:204`](../../src/application/automation/backfill_service.py#L204) | Resume parent sau Guided Review, không tạo post-approval run thứ hai | Cùng backfill run |
| `execute_ordered_backfill` | [`backfill_runner.py:23`](../../src/application/automation/backfill_runner.py#L23) | Xử lý từng ngày theo thứ tự và giữ scheduled checkpoint tách biệt | Per-day outcome |
| `reconciliation_ingestion` | [`reconciliation_ingestion.py:301`](../../dags/reconciliation_ingestion.py#L301) | Khai báo DAG control plane cho scheduled stream và backfill | `_execute_stream` / `_execute_backfill` |
| `_execute_stream` | [`reconciliation_ingestion.py:101`](../../dags/reconciliation_ingestion.py#L101) | Gọi application entrypoint cho một mapped stream task | Runtime result |
| `_execute_backfill` | [`reconciliation_ingestion.py:120`](../../dags/reconciliation_ingestion.py#L120) | Gọi ordered backfill và cập nhật parent progress | Backfill result |

## 6. Lifecycle, outcome và cleanup

| Hàm | Vị trí | Trách nhiệm |
|---|---|---|
| `StreamLifecycle.mark_ingesting` | [`stream_lifecycle.py:135`](../../src/application/automation/stream_lifecycle.py#L135) | Chuyển runtime sang giai đoạn ingest và ghi attempt event | Runtime timeline |
| `finish_source_stream_run` | [`stream_runtime.py:59`](../../src/application/automation/stream_runtime.py#L59) | Persist attempt/outcome cuối cùng, gồm lỗi Airflow có thể hành động | Runtime history |
| `cleanup_source_unit` | [`stream_ingestion.py:92`](../../src/application/automation/stream_ingestion.py#L92) | Dọn file tạm sau khi unit đã được xử lý hoặc thất bại | Source retention contract |
| `AutomationJobCommandService.run_now` | [`job_commands.py:274`](../../src/application/automation/job_commands.py#L274) | Tạo manual runtime và trigger workflow | Schedules UI/API |
| `AutomationJobCommandService.retry` | [`job_commands.py:331`](../../src/application/automation/job_commands.py#L331) | Retry runtime/checkpoint qua operator action | Recovery UI/API |
| `AutomationJobCommandService.resolve` | [`job_commands.py:418`](../../src/application/automation/job_commands.py#L418) | Resolve blocked unit với action và operator identity | Resume/skip |

## 7. Thứ tự trace core

```text
execute_stream
  → run_source_stream
  → StreamLifecycle.start
  → stream_identity
  → IngestionCheckpointRepository.find_by_stream
  → select_stream_runner
      → run_paginated_stream / run_file_stream
      → stage_stream_unit (API)
      → process_source_units
          → claim_unit
          → run_ingestion
          → mark_completed
          → advance
  → StreamLifecycle.finish
```

Airflow chỉ là workflow/control-plane adapter; checkpoint, raw staging,
mapping gate, ingestion và reconciliation vẫn thuộc application/domain/
infrastructure. File này là index của core flow, không thay thế acceptance
evidence trong [Sprint 2](sprint-2-incremental-recovery.md) và [Sprint 2.5](sprint-2.5-airflow-migration.md).
