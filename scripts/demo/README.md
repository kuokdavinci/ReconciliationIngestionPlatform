# Demo scripts

Mọi demo fixture có thể chạy, scenario seed và evaluation command nằm ở đây.
Production module nằm trong `src/`; automated test nằm trong `tests/`; benchmark
và generic data-generation script nằm ngoài thư mục này.

## Cấu trúc

- `sprint1/` — MOMO E2E/idempotency demo seed.
- `sprint2/` — ViettelPay pagination, checkpoint recovery fixture, evaluation,
  reset command và VNPAY FileDrop ordered-backfill fixture.
- `scenarios/` — ACMEPAY scheduler, VNPAY audit-flow, ZaloPay AI và healthy
  dashboard demo seed.

Command thường dùng được expose qua Makefile. Chạy trực tiếp từ repository root
dùng `PYTHONPATH=.`.

API image đóng gói demo script lúc build. Sau khi thay đổi hoặc thêm fixture,
rebuild image một lần trước khi chạy reset target:

```bash
docker compose build api
docker compose up -d --no-build api
```

## VNPAY FileDrop backfill

Reset deterministic fixture, có thể override inclusive business-date range:

```bash
VNPAY_BACKFILL_FROM=2026-08-07 \
VNPAY_BACKFILL_TO=2026-08-12 \
make vnpay-backfill-reset
```

Sau đó mở Schedules UI, start VNPAY Backfill, approve mapping đang pending
trong Guided Review và theo dõi ordered day progress panel. Packet gồm ba
internal PostgreSQL preview row cho working day đầu tiên. FileDrop pattern có
scope theo ngày nên delivery của ngày sau không bị consume trước backfill day.
