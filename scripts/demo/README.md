# Demo scripts

All runnable demo fixtures, scenario seeds, and evaluation commands live here.
Production modules stay under `src/`; automated tests stay under `tests/`;
benchmark and generic data-generation scripts stay outside this directory.

## Layout

- `sprint1/` — MOMO E2E/idempotency demo seed.
- `sprint2/` — ViettelPay pagination, checkpoint recovery fixture, evaluation,
  reset command, and the VNPAY FileDrop ordered-backfill fixture.
- `scenarios/` — ACMEPAY scheduler, VNPAY audit-flow, ZaloPay AI, and healthy
  dashboard demo seeds.

Typical commands are exposed through the Makefile. Direct execution from the
repository root uses `PYTHONPATH=.`.

The API image packages demo scripts at build time. After changing or adding a
fixture, rebuild the image once before running the reset target:

```bash
docker compose build api
docker compose up -d --no-build api
```

## VNPAY FileDrop backfill

Reset the deterministic fixture, optionally overriding the inclusive business
date range:

```bash
VNPAY_BACKFILL_FROM=2026-08-07 \
VNPAY_BACKFILL_TO=2026-08-12 \
make vnpay-backfill-reset
```

Then open the Schedules UI, start VNPAY Backfill, approve the pending mapping in
Guided Review, and follow the ordered day progress panel. The packet includes
three internal PostgreSQL preview rows for the first working day. The FileDrop
pattern is date-scoped so a later delivery is not consumed before its backfill
day.
