# Sprint 4 — Baseline review: Fraud Detection 100k

**Trạng thái:** `completed`

- Dataset SHA-256: `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6`
- Boundary: `IngestionPipeline.process_file`
- PostgreSQL persistence: `LOGGED`; không đổi schema/index.
- Timer đo `process_file()`; `tracemalloc` không nằm trong wall-clock.

## Baseline

- Variant: `control-20k-w1`, batch `20000`, `write_workers=1`,
  `fast_mode=false`.
- Samples: `5`.
- DB writes: `5`.
- Wall-clock median/MAD: `11581.117/321.679 ms`
- Peak RSS median/max: `243941376/244420608 bytes`

## Components

| Component | Median (ms) |
|---|---:|
| `copyMs` | 445.505 |
| `insertClassifyMs` | 3206.619 |
| `mappingMs` | 418.043 |
| `persistenceWindowMs` | 10166.725 |
| `slowestBatchMs` | 1072.685 |
| `stageSetupMs` | 16.804 |
| `totalBatchWallMs` | 4750.992 |
| `transactionOverheadMs` | 89.735 |
| `tupleMaterializationMs` | 554.687 |

`db_insert_ms` vẫn là persistence window tương thích ngược, không phải
SQL-only time. Raw samples và correctness counters được giữ trong JSON
benchmark artifact.
