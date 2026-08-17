# Sprint 2 — Core Runtime Index

Sprint 2 và Sprint 2.5 hợp nhất xoay quanh một runtime ingestion có thể retry,
replay và vận hành an toàn qua Airflow.

## 1. Các lớp chính

| Lớp | Trách nhiệm cốt lõi |
|---|---|
| Domain & core | Model, enum, identity, retry policy và các port/contract ổn định |
| Application | Automation stream, ingestion, checkpoint, review/replay, reconciliation và ordered backfill |
| Adapters | FastAPI, API/FileDrop/SFTP fetchers, readers, Mongo/PostgreSQL repositories và Airflow gateway |
| Control plane | Airflow quản lý schedule, dependency, retry/timeout, pool và task state; business logic vẫn ở application |

## 2. Luồng xử lý cốt lõi

```text
source
  → source identity / claim
  → fetch và stage raw units
  → mapping/config gate
      ├─ review packet → approval → replay staged units
      └─ approved mapping → ingestion
  → transaction write / reconciliation
  → checkpoint và runtime outcome
```

API pagination stage toàn bộ stream trước khi ingest. FileDrop/SFTP xử lý các
source unit theo thứ tự. Backfill tạo một parent run, mở rộng thành các ngày
nghiệp vụ và resume cùng parent sau approval.

## 3. Các invariant phải giữ

- Idempotency đi theo nhiều lớp: `fileHash`, `fetchUnitKey`, checkpoint và
  `ingestion_key`.
- API dùng `metadata.sourceUnitKey` explicit khi có; nếu không có thì tạo
  identity hash ổn định từ metadata fetch.
- Raw stage API đã completed phải trả `SAFE_DUPLICATE`/
  `streamAlreadyCompleted` trước khi fetch lại hoặc tạo review mới.
- Review packet chỉ được collapse khi cùng source scope
  (`rawStageKey`, `backfillRunId` hoặc source-file identity); cùng mapping
  structure không đồng nghĩa cùng delivery.
- Approval replay phải chốt checkpoint và high-water mark sau khi ingestion
  hoàn tất.
- Scheduled và backfill dùng stream/checkpoint riêng; ordered backfill dừng ở
  boundary đầu tiên bị lỗi hoặc cần review.
- Mongo unique index `fetchUnitKey` chỉ áp dụng cho giá trị kiểu string để
  document null/missing không va chạm.

## 4. Runtime outcomes

| Outcome | Ý nghĩa vận hành |
|---|---|
| `COMPLETED` / `NO_DATA` | Stream kết thúc bình thường, có hoặc không có dữ liệu |
| `WAITING_REVIEW` | Đã stage đủ dữ liệu nhưng cần mapping/operator approval |
| `BLOCKED` / `FAILED` | Cần recovery, retry hoặc operator resolve |
| `SAFE_DUPLICATE` | Source stream đã hoàn tất; lần chạy lại được bỏ qua an toàn |

## 5. Canonical implementation map

| Capability | Module chính |
|---|---|
| Stream execution | [`src/application/automation/stream_runner.py`](../../src/application/automation/stream_runner.py) và [`stream_runtime.py`](../../src/application/automation/stream_runtime.py) |
| Source-unit ingestion | [`src/application/ingestion/source_unit_orchestrator.py`](../../src/application/ingestion/source_unit_orchestrator.py) |
| Checkpoint/recovery | [`src/infrastructure/ingestion/checkpoint_repository.py`](../../src/infrastructure/ingestion/checkpoint_repository.py) |
| Review/replay | [`src/application/review/`](../../src/application/review/) |
| Ordered backfill | [`src/application/automation/backfill_service.py`](../../src/application/automation/backfill_service.py) và [`backfill_runner.py`](../../src/application/automation/backfill_runner.py) |
| Shared utilities and domain models | [`src/core/utils.py`](../../src/core/utils.py) và [`src/domain/`](../../src/domain/) |
| Workflow/persistence adapters | [`dags/reconciliation_ingestion.py`](../../dags/reconciliation_ingestion.py), [`src/infrastructure/workflows/`](../../src/infrastructure/workflows/) và [`src/infrastructure/persistence/`](../../src/infrastructure/persistence/) |

Các helper cũ như `stream_staging.py`, `stream_review_gate.py`,
`stream_fetching.py` và các utility core nhỏ chỉ là compatibility re-export;
không xem chúng là nơi triển khai logic mới.

Chi tiết acceptance và evidence nằm trong [Sprint 2](sprint-2-incremental-recovery.md)
và [Sprint 2.5](sprint-2.5-airflow-migration.md).
