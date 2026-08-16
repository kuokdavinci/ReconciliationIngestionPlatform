# Known Issues và Operational Constraints

**Cập nhật:** 2026-08-14

## Môi trường

- Shell command trong workspace chạy qua `rtk` theo quy ước repo.
- Sandbox có thể gặp lỗi `bwrap: loopback: Failed RTM_NEWADDR`; đó là giới hạn runtime, không mặc định là lỗi ứng dụng.
- Nếu command bị sandbox chặn, cần dùng escalation được phê duyệt thay vì đổi code để né policy.
- Next.js production build dùng Webpack (`next build --webpack`); không đổi sang Turbopack nếu chưa có verification tương đương.

## Airflow pilot

- Compose pilot đang manual-only với `AIRFLOW_GLOBAL_SCHEDULE=none`; production schedule chưa được bật mặc định.
- `AIRFLOW_TASK_RETRIES=0` để recovery do operator thực hiện và giữ checkpoint semantics rõ ràng.
- Live health, DAG import, page failure/resume, same-DAG-run retry và ordered backfill cần evidence từ môi trường Docker thật; unit/architecture tests không thay thế evidence này.
- Không bật thêm scheduler owner cho cùng stream. Rollback pilot là pause DAG và rollback application artifact.
- Sprint 2.5 còn 5 business-acceptance mục partial/pending: multi-fingerprint
  FileDrop/SFTP recovery ordering, full bounded retry matrix,
  `BLOCKED`/resolve/skip/`WAITING_REVIEW` live state semantics, concurrent
  scheduled-checkpoint isolation khi backfill và rollback per partner không
  reset dữ liệu. Contract tests và current-image smoke evidence đã được ghi ở
  `docs/phase-2/sprint-2.5-airflow-migration.md`.
- Recovery hardening đã có live ViettelPay retry/recovery và current-image VNPAY
  approved-mapping backfill smoke evidence; full FileDrop/SFTP, retry/state,
  concurrent isolation và production rollback evidence vẫn mở.

## CI và tài liệu

- Codegraph hiện không có `src/scheduler/`, `src/services/` hoặc `frontend/`; một số historical plan/report và workflow cũ còn nhắc tên legacy này. Khi chỉnh CI tiếp theo, cần dọn các path legacy trong `.github/workflows/ingestion-pipeline.yml`.
- `docs/phase-2/sprint-2.6-recovery-hardening.md` giữ tên file để bảo toàn link lịch sử, nhưng nội dung đã được hợp nhất vào Sprint 2.5 và không phải sprint độc lập.
- Sau thay đổi cấu trúc, chạy `codegraph sync .` và cập nhật `README.md`, `docs/INDEX.md`, architecture/module/CI docs nếu cần.

## Test dependencies

- Ứng dụng import `httpx` trực tiếp và Starlette `1.3.x` dùng `httpx2` cho ASGI test client; phải giữ cả `httpx` và `httpx2>=2.0.0`.
- Không gọi `fastapi.testclient.TestClient` trong event loop đang chạy. Test async dùng `httpx2.AsyncClient` + `httpx2.ASGITransport` và `base_url`.
- Real LLM E2E cần credential thật; quality gate dùng fake key và test provider/guardrail không gọi real model.
- `mongo-express` trong Compose tắt basic auth cho local convenience; chỉ bind local và không coi đó là production config.

## Follow-up

- Thu thập live acceptance evidence đầy đủ cho Sprint 2.5.
- Dọn các workflow path legacy trong CI.
- Hoàn thiện kế hoạch Sprint 3 data quality/quarantine và Sprint 4 observability.
- Giữ `TODO.md` làm nguồn công việc sản phẩm chưa giải quyết.
