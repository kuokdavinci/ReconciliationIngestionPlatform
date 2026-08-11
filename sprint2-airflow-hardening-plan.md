# Sprint 2 / 2.5 Recovery Hardening Plan

**Status:** Complete; final verification passed. Live Airflow rollout remains environment-dependent.
**Canonical progress:** [Sprint 2.6 recovery hardening](docs/phase-2/sprint-2.6-recovery-hardening.md)

## Goal

Make Airflow and the application share one scheduler owner, preserve recovery
attempt history when a retry reuses the same runtime, and make review counts
cover the complete staged API stream.

## Tasks

- [x] P0: enforce one scheduler owner and add regression coverage.
- [x] P0: persist runtime attempt events and expose them in the recovery drawer.
- [x] P0: show pre-checkpoint durable-staging failures in recovery status/events.
- [x] P1: count all raw staged pages and use UTC-normalized business-day bounds.
- [x] P1: mark manual runtime failures when Airflow selection/config validation fails.
- [x] P1: normalize reconciliation keys, SQL statuses and result ordering.
- [x] P1: add PostgreSQL composite indexes and migration `0003`.
- [x] P2: align Airflow retry gating with configured retry count and update runbook.
- [x] Verification: backend/frontend checks, Compose validation, docs links and codegraph refresh.

## Done when

- Airflow and APScheduler cannot own the same schedule in the same Compose mode.
- A fail → retry → success sequence retains both attempts in the recovery view.
- A three-page staged stream reports all records and internal rows for the same
  Asia/Ho_Chi_Minh business date.
- Airflow selection/config failures end the application runtime as `FAILED`.
- Progress and remaining live-verification work are recorded in the Sprint 2.6
  progress document.
