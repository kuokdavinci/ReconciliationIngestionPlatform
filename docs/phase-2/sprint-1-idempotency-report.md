# Báo cáo Sprint 1 — Tính Idempotency và Ngăn ngừa trùng lặp

> **Nhánh:** `phase2/sprint-1`
> **Phạm vi:** replay file, replay fetch-unit, loại bỏ giao dịch trùng và ghi dữ liệu an toàn khi xảy ra conflict
> **Trạng thái:** ✅ **PASS** — đã triển khai và xác minh; benchmark ghi nhận 13/13 kịch bản PASS.

## Tóm tắt

Sprint 1 bổ sung các ranh giới idempotency cho pipeline ingestion:

- Claim file atomically bằng `fileHash` và claim fetch-unit bằng `fetchUnitKey`.
- Giao dịch partner trong PostgreSQL có `ingestion_key` bắt buộc, duy nhất theo `(identify, ingestion_key)`.
- Ghi batch bằng `ON CONFLICT DO NOTHING`, kèm thống kê `inserted`, `duplicates` và `failed`.
- Suy ra key deterministic; payload không có định danh hợp lệ sẽ bị từ chối.
- Seed E2E MOMO cho trường hợp trùng một phần: 20 dòng cũ và 10 dòng mới.

Incremental recovery, quarantine dữ liệu lỗi và observability thuộc các sprint Phase 2 tiếp theo.

## Các thành phần đã review

| Khu vực | Thành phần | Kết quả |
|---|---|---|
| Schema | `alembic/versions/0002_ingestion_idempotency.py` | Thêm `ingestion_key` và hợp đồng uniqueness trong PostgreSQL. |
| Persistence | `src/models/postgres.py`, `src/models/data_container.py` | Repository giao dịch PostgreSQL và ghi batch an toàn khi conflict. |
| Claim | `src/models/reconciliation_file.py`, `src/models/indexes.py` | Cơ chế atomic create-or-get cho file/fetch-unit. |
| Pipeline | `src/pipeline/ingestion_pipeline.py`, `src/core/types.py` | Suy ra key, xử lý replay và thống kê chi tiết. |
| Runtime | `src/fetchers/*`, `src/application/automation/stream_runner.py`, `src/api/automation.py` | Truyền metadata idempotency và công bố duplicate outcome. |
| E2E | `scripts/demo/sprint1/seed_momo_e2e.py`, `tests/test_sprint1_eval_benchmark.py` | Helper seed và bộ đánh giá Sprint 1. |

## Hợp đồng idempotency

Replay file bị chặn bởi claim `fileHash` canonical. Replay API page bị chặn bởi `fetchUnitKey`, kể cả khi payload hoặc tên file khác nhau. Khi replay, hệ thống trả về record canonical đã tồn tại.

Với giao dịch, pipeline suy ra `ingestion_key` ổn định từ hợp đồng định danh partner. Hệ thống ném `ValueError` khi không có định danh; không tạo key fallback ngẫu nhiên. PostgreSQL bảo vệ uniqueness theo partner bằng `(identify, ingestion_key)`.

Conflict trong batch được bỏ qua ở ranh giới database và tính là duplicate, thay vì làm toàn bộ batch thất bại.

## Bản đồ triển khai theo function

| Function | Vai trò trong hợp đồng idempotency |
|---|---|
| `IngestionPipeline._compute_file_hash()` | Tính identity SHA-256 ổn định để bảo vệ chống replay file. |
| `IngestionPipeline._derive_fetch_unit_key()` | Kiểm tra và suy ra identity ổn định cho API page, cursor hoặc fetch window. |
| `IngestionPipeline._derive_ingestion_key()` | Suy ra identity giao dịch và từ chối payload không có định danh hợp lệ. |
| `IngestionPipeline.process_file()` | Điều phối claim, parse, suy ra key, ghi batch, tính duplicate, cập nhật trạng thái và xử lý lỗi. |
| `ReconciliationFileRepository.create_or_get_by_file_hash()` | Tạo claim file canonical atomically hoặc trả record file/fetch-unit hiện có sau race replay. |
| `ReconciliationFileRepository.find_by_file_hash()` | Tra cứu claim file canonical bằng SHA-256. |
| `ReconciliationFileRepository.find_by_fetch_unit_key()` | Tra cứu claim canonical của fetch-unit API. |
| `DataContainerRepository.insert_many()` | Ghi transaction partner bằng PostgreSQL `ON CONFLICT DO NOTHING` và trả số inserted/duplicate. |
| `IngestionPipeline._record_batch_result()` | Tổng hợp `inserted`, `duplicates`, `failed` mà không biến duplicate thành lỗi batch. |
| `DataContainerRepository.rebind_source_file_by_ingestion_keys()` | Gắn lại các transaction đã tồn tại vào logical file hiện tại sau replay trùng một phần. |
| `stream_ingestion.fetch_unit_metadata()` | Truyền identity endpoint/page/cursor/window từ application runner vào ingestion. |
| `stream_runner.run_source_stream()` và `stream_ingestion.run_ingestion()` | Truyền context fetch-unit vào pipeline và lưu duplicate outcome cho vận hành. |

## Demo MOMO

```bash
make momo-e2e-reset
make momo-e2e-run
make momo-e2e-phase2
make momo-e2e-run
```

Để chuẩn bị riêng kịch bản trùng một phần:

```bash
PYTHONPATH=. python scripts/demo/sprint1/seed_momo_e2e.py phase2_duplicate
```

File thứ hai gồm 20 dòng cũ và 10 dòng mới. Kết quả kỳ vọng là insert 10 dòng, bỏ qua 20 dòng duplicate và không tạo transaction trùng. Các lệnh này xóa dữ liệu demo theo partner, chỉ chạy trên môi trường test/demo.

## Bằng chứng

- [Đặc tả benchmark](sprint-1-eval-benchmark.md)
- [Kết quả chạy benchmark](sprint-1-eval-benchmark-run.md)
- [Ghi chú triển khai](sprint-1-idempotency.md)

Bản chạy thực tế bao phủ schema, insert ban đầu, file replay, conflict một phần/toàn phần, invariant duplicate, kiểm tra key deterministic, an toàn migration, lưu transaction trong PostgreSQL, concurrent file claim và fetch-unit replay.

## Kết quả xác minh hiện tại

| Hạng mục | Kết quả | Ghi chú |
|---|---|---|
| Nhánh và working tree | PASS | `phase2/sprint-1`; sạch trước khi chỉnh tài liệu. |
| Sprint benchmark | PASS | Chạy với `UV_CACHE_DIR` local và Docker PostgreSQL/Mongo; `1 passed in 0.68s`, dùng database `reconciliation_test`. |
| Tài liệu | PASS | Nội dung khớp tên migration, phạm vi, dữ liệu demo và trạng thái xác minh thực tế. |

Lệnh chạy lại benchmark:

```bash
UV_CACHE_DIR=$PWD/.uv-cache uv run python -m pytest tests/test_sprint1_eval_benchmark.py -q
```

## Kết luận review

Triển khai Sprint 1 dùng database constraint làm ranh giới bảo vệ duplicate cuối cùng và tách riêng identity của file, fetch-unit và transaction. Benchmark đã được xác minh thành công trên PostgreSQL/Mongo trong Docker, sử dụng `reconciliation_test`.
