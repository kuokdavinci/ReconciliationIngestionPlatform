# MOMO Reconciliation E2E Test & Mocking Guide

This guide defines a safer E2E plan for **MOMO** so the mock data matches the reconciliation logic that is actually running in the system.

The key rule is simple:

* `Command Center` reads from `reconciliation_result`, not directly from `internal_transaction`.
* `reconciliation_result` is produced from **partner rows ingested for the day** plus **internal rows in finalized states** (`SUCCESS`, `FAILED`, `REVERSED`).
* If you seed more finalized internal rows than the partner file actually contains, the engine will correctly generate `MISSING_PARTNER`.

That means a "green" scenario must never preload unrelated finalized internal rows for the same `partner + date`.

---

## Quick Start

The canonical seed script is [`scripts/demo/sprint1/seed_momo_e2e.py`](../../scripts/demo/sprint1/seed_momo_e2e.py). Do **not** use the legacy `seed_momo_scheduler_green.py`.

### Happy path — exact retry steps

1. Reset Phase 1 data:

```bash
make momo-e2e-reset
```

2. Trigger automation so the missing config creates a pending review packet:

```bash
make momo-e2e-run
```

3. In the UI, open the MOMO packet in `Review Queue` and approve it.
   Scope expectation:
   `FULL_SNAPSHOT`

4. Verify Phase 1 result.
   Expected:
   * `20 MATCHED`
   * `0 MISSING_PARTNER`

5. Prepare Phase 2 data:

```bash
make momo-e2e-phase2
```

6. Trigger automation again:

```bash
make momo-e2e-run
```

7. Verify Phase 2 result.
   Scope expectation:
   `INCREMENTAL_APPEND`

   Expected:
   * current run reconciles only wave2 keys `MOMO_TXN_9100..MOMO_TXN_9119`
   * `20 MATCHED`
   * `0 MISSING_PARTNER`

Use this to inspect the job after each run if needed:

```bash
make momo-e2e-job
```

### Missing-partner demo

1. Prepare the baseline and anomaly:

```bash
make momo-e2e-reset
make momo-e2e-missing-partner-demo
```

2. Trigger automation:

```bash
make momo-e2e-run
```

3. In the UI, approve the packet and keep the proposed scope as:
   `FULL_SNAPSHOT`

4. Expected:
   * `20 MATCHED`
   * `1 MISSING_PARTNER`
   * missing key: `MOMO_TXN_90_MISSING_PARTNER`

### Fast checks

- If you see unexpected `MISSING_PARTNER` rows right after `make momo-e2e-reset`, you are likely still running the old seed flow or approving with the wrong packet/file.
- If Phase 2 still shows wave1 rows in the current run, verify the packet/file scope is `INCREMENTAL_APPEND`.
- For the full target list, run `make momo-e2e-help`.

---

## 1. What Went Wrong In The Old Plan

The previous plan seeded:

* `40` finalized internal records for the same day
* but the first partner file only contained `19` rows

That setup does **not** represent "20/20 reconciled". It represents:

* `19` partner-side rows available for reconciliation
* `21` internal finalized rows with no partner-side match

So the engine correctly produces a mixed snapshot such as:

* `MATCHED`
* `AMOUNT_MISMATCH`
* `MISSING_PARTNER`

If the test goal is "green dashboard after approval", the seed must be aligned with the exact file content for that phase.

---

## 2. Correct E2E Modes

Use one of these modes explicitly. Do not mix them.

### Mode A: Green Baseline

Goal:

* partner file and internal DB represent the same transaction set
* after approval and immediate reconciliation, `Command Center` should show only the intended outcomes for that exact set

Rules:

* seed only the internal rows that exist in the current partner file
* do not preload the next wave into finalized internal state
* do not include internal-only anomaly rows unless the test explicitly needs them

Expected result:

* total reconciliation count matches the file dataset for that wave

### Mode B: Incremental Wave

Goal:

* verify a second file can be ingested after config approval without going back through review

Rules:

* Phase 1: seed internal rows only for Wave 1
* approve config and reconcile Wave 1
* Phase 2: add the Wave 2 internal rows, replace the file with the Wave 2 partner rows, then run automation again
* each wave must remain internally consistent with its own file

Expected result:

* after each run, reconciliation reflects the currently seeded and intended dataset, not unrelated future rows

### Mode C: Intentional Missing Partner

Goal:

* verify that internal-only finalized transactions become `MISSING_PARTNER`

Rules:

* add internal finalized rows that are intentionally absent from the partner file
* document those keys explicitly in the scenario

Expected result:

* `MISSING_PARTNER` is expected and should appear in both `Reconciliation` and `Command Center`

---

## 3. Ground Truth Rules For Mock Data

These rules must hold for every MOMO E2E setup.

1. Partner file keys and internal keys must come from the same planned key range.
2. A "green" run must not preload extra finalized internal keys for the same day.
3. If you want to simulate future internal records, keep them out of the current reconciliation slice.
4. `PENDING` internal transactions are ignored upstream by `ReconciliationEngine`, so they are safe if you need placeholders that must not produce `MISSING_PARTNER`.
5. Any internal row in `SUCCESS`, `FAILED`, or `REVERSED` is eligible for reconciliation on that day.

---

## 4. Recommended Data Shapes

### Green Baseline Dataset

Use one exact range for both sources:

* partner file: `MOMO_TXN_9000` to `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` to `MOMO_TXN_9019`

Optional:

* include `1` intentional amount mismatch inside the same range
* if you do, the expected total is still `20`, but the status breakdown is no longer fully matched

Do not include:

* `MOMO_TXN_9100` to `MOMO_TXN_9119`
* `MOMO_TXN_90_MISSING_PARTNER`

### Incremental Two-Wave Dataset

Wave 1:

* partner file: `MOMO_TXN_9000` to `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` to `MOMO_TXN_9019`

Wave 2:

* partner file: `MOMO_TXN_9100` to `MOMO_TXN_9119`
* internal DB: `MOMO_TXN_9100` to `MOMO_TXN_9119`

Important:

* do not seed Wave 2 internal rows during Wave 1 if the test expectation is a clean Wave 1 dashboard

### Intentional Missing Partner Dataset

Base set:

* partner file: `MOMO_TXN_9000` to `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` to `MOMO_TXN_9019`

Add anomaly:

* internal DB only: `MOMO_TXN_90_MISSING_PARTNER`

Expected:

* total reconciliation count becomes `21`
* one row is `MISSING_PARTNER`

---

## 5. Seed Script Guidance

Canonical script:

* [scripts/demo/sprint1/seed_momo_e2e.py](../../scripts/demo/sprint1/seed_momo_e2e.py)

This is the single source of truth for MOMO E2E seed data. It supports three explicit modes:

* `reset` — wipe MOMO internal rows, seed the 20 wave1 rows (`MOMO_TXN_9000`..`MOMO_TXN_9019`), and write a partner xlsx with the same 20 keys. Use this for a clean Phase 1 baseline.
* `phase2` — add the 20 wave2 internal rows (`MOMO_TXN_9100`..`MOMO_TXN_9119`) and **overwrite** the partner file with the wave2 keys. Combined with `reset`, this is the 2-command happy path described in the Quick Start.
* `missing_partner_demo` — insert a single `MOMO_TXN_90_MISSING_PARTNER` internal row (50000 VND, `SUCCESS`, same day) and write a wave1-only partner xlsx. A subsequent `FULL_SNAPSHOT` ingestion produces exactly `20 MATCHED + 1 MISSING_PARTNER`.

The corresponding `make` targets (`momo-e2e-reset`, `momo-e2e-phase2`, `momo-e2e-missing-partner-demo`) wrap each mode and are the recommended entry points — see the Quick Start above.

### Legacy script — do not use

The former `seed_momo_scheduler_green.py` flow is removed. If a stale E2E fixture still references it, replace that invocation with the canonical script above.

---

## 6. Recommended E2E Flow

### Scenario 1: Config Approval + Clean Reconciliation

Goal:

* validate mapping approval flow
* validate immediate reconciliation after approval
* validate `Command Center` totals against the partner file dataset only

Plan:

1. Clean MOMO collections for the target day.
2. Seed only Wave 1 internal rows: `MOMO_TXN_9000` to `MOMO_TXN_9019`.
3. Generate partner file with the same Wave 1 keys.
4. Run automation once so the missing config creates a pending review packet.
5. Approve config with runtime validation.
6. Let the system re-ingest and reconcile immediately.
7. Verify `reconciliation_result.total == 20`.

Expected:

* no accidental `MISSING_PARTNER` from future-wave rows

### Scenario 2: Incremental Second Wave

Goal:

* validate approved config is reused without review

Plan:

1. Complete Scenario 1 first.
2. Add only Wave 2 internal rows: `MOMO_TXN_9100` to `MOMO_TXN_9119`.
3. Replace the partner file with Wave 2 keys.
4. Run automation again.
5. Verify the second run completes without review packet creation.
6. Verify reconciliation matches the intended Wave 2 slice.

Recommended verification:

* check key overlap explicitly, not just counts

### Scenario 3: Intentional Missing Partner

Goal:

* validate discrepancy behavior

Plan:

1. Seed the matched base set.
2. Add a small number of extra finalized internal rows.
3. Keep them out of the partner file.
4. Reconcile.

Expected:

* `MISSING_PARTNER` appears by design
* `Command Center` and `Reconciliation` should both reflect those rows

---

## 7. Verification Checklist

Before concluding a run, verify all three layers:

### Partner-side ingestion

Check:

* `reconciliation_file.processingStatus == COMPLETED`
* `data_container` row count for `partner + date`
* the actual `partnerData.trace` values ingested

### Internal-side eligibility

Check:

* `internal_transaction` count for `partner + date`
* status breakdown of those rows
* whether any extra finalized keys exist outside the intended partner file range

### Reconciliation output

Check:

* `reconciliation_result` total count
* status breakdown
* exact key set for `MISSING_PARTNER`

If the dashboard shows more records than expected, the first thing to check is not the UI. It is whether `reconciliation_result` already contains extra finalized internal-only keys for that day.

---

## 8. Operator Commands

### Shortcut targets

```bash
make momo-e2e-help                # list all MOMO E2E targets (Quick Start at the top)
make momo-e2e-reset               # clean Phase 1 (20 internal rows 9000-9019 + partner file)
make momo-e2e-phase2              # add Phase 2 (20 internal rows 9100-9119 + new partner file)
make momo-e2e-missing-partner-demo  # inject MOMO_TXN_90_MISSING_PARTNER for engine demo
make momo-e2e-run                 # trigger MOMO automation run
make momo-e2e-job                 # inspect MOMO automation job
make momo-e2e-phase2-file         # write Wave 2 partner file (9100-9119) only
make momo-e2e-rebuild             # rebuild api + scheduler containers
```

### Trigger automation run

```bash
curl -s -X POST http://localhost:8000/api/v1/automation/jobs/MOMO/run | jq .
```

### Inspect MOMO automation job

```bash
curl -s http://localhost:8000/api/v1/automation/jobs | jq '.jobs[] | select(.partner == "MOMO")'
```

### Rebuild backend containers after logic changes

```bash
docker compose up -d --build api scheduler
```

---

## 9. Final Recommendation

For MOMO E2E, treat "green baseline" and "missing partner demo" as two different fixtures.

Do not use one shared seed that:

* preloads future-wave finalized rows
* writes only a partial partner file
* but still expects a clean `Command Center`

That fixture is internally inconsistent with the reconciliation engine and will keep producing confusing totals.
