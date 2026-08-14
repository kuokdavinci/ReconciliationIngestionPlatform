# Safe Hotspot Cleanup Design

## Goal

Tiếp tục dọn các phần còn sót của đợt tái cấu trúc mà không làm tăng số lớp trung gian, không thay đổi public API và vẫn giữ workflow CI có thể chạy độc lập trên GitHub Actions.

## Scope

### 1. Review packet ownership

`src/api/review_packets.py` chỉ nhận request, load mapping và gọi application service. Logic dựng `ReviewPacket` cho luồng Mapping Studio handoff sẽ thuộc `src/application/review/proposal_creation.py`, dùng repository được truyền vào để giữ khả năng test và compatibility.

### 2. Legacy `PartnerData`

Production đã dùng `src.domain.partner_transaction.models.PartnerData`. Các test còn import `src.core.types.PartnerData` sẽ chuyển sang domain model, sau đó xoá class trùng khỏi `src/core/types.py`. Không tạo alias mới trong `core`.

### 3. API fetcher decomposition

Giữ `APIFetcher` làm public entry point. Tách `_fetch_paginated` theo các helper thuần, giới hạn ở các trách nhiệm đã có sẵn:

- dựng metadata/source unit cho page;
- chuẩn hoá response và pagination payload;
- ghi nhận kết quả page và tạo `FetchResult`.

Không thêm strategy class, state machine hoặc abstraction mới. Hành vi retry, cursor loop, status/error code, file output và metadata phải giữ nguyên.

### 4. Test suite and CI

Audit các test APIFetcher và model legacy để loại bỏ test trùng hành vi, không xoá test chỉ vì tên tương tự. Giữ lại test chuyên về contract/architecture và test regression cho pagination, retry, cursor failure, file output và domain `PartnerData`.

Workflow backend phải tiếp tục chạy lint, mypy, migration và backend tests. Workflow ingestion phải tiếp tục chạy lint và toàn bộ nhóm ingestion/e2e hiện được chỉ định. Chỉ sửa workflow nếu phát hiện command hoặc phạm vi test không còn khớp với cấu trúc hiện tại.

## Explicitly deferred

Không gom `src/infrastructure/persistence` với `src/infrastructure/postgres` trong change này vì sẽ cần migration rộng hoặc compatibility facade. Không tiếp tục tách sâu `document_executor`, `paginated_stream_runner`, `source_unit_orchestrator`, `job_queries` và `analysis/insights` nếu việc tách chỉ chuyển code giữa file mà không tạo boundary dễ kiểm chứng.

## Verification

- Chạy test đỏ trước mỗi thay đổi hành vi/ownership mới.
- Chạy test scope sau từng task.
- Chạy `ruff`, `mypy`, `git diff --check`.
- Chạy đúng command test của `.github/workflows/backend-quality.yml` và `.github/workflows/ingestion-pipeline.yml` ở mức môi trường local tương đương.
- Refresh codegraph sau khi thay đổi cấu trúc hoặc import.
