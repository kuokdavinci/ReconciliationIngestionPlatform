# Demo scripts

All runnable demo fixtures, scenario seeds, and evaluation commands live here.
Production modules stay under `src/`; automated tests stay under `tests/`;
benchmark and generic data-generation scripts stay outside this directory.

## Layout

- `sprint1/` — MOMO E2E/idempotency demo seed.
- `sprint2/` — ViettelPay pagination, checkpoint recovery fixture, evaluation,
  and reset command.
- `scenarios/` — ACMEPAY scheduler, VNPAY audit-flow, ZaloPay AI, and healthy
  dashboard demo seeds.

Typical commands are exposed through the Makefile. Direct execution from the
repository root uses `PYTHONPATH=.`.
