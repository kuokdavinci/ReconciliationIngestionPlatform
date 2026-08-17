# Baseline Sprint 3 — IBM AML-LI

File baseline canonical để đối chiếu regression ingestion trong Sprint 3.

## Trạng thái và phạm vi

- Trạng thái: **frozen**.
- Boundary: `IngestionPipeline.process_file`.
- Dataset: `data/eda/ibm_aml_li/raw/LI-Small_Trans.csv`.
- SHA-256: `f7a9940339c78b5d1476071505b5867c0f531bf965319d`.
- Freeze commit: `ff4d6b925932892c4574089fb34f88466803aea0`.

Không bao gồm dataset preparation, startup/migration, reconciliation,
quality rules, API/Airflow và quarantine reprocess.

## Cấu hình freeze

```text
batch_size=20,000
write_workers=1
ordered_insert=false
fast_mode=false
quality_rules=false
```

`From Account` đang được dùng làm ingestion key. Vì vậy duplicate là behavior
của mapping hiện tại, chưa phải kết quả của quality rule.

## Kết quả baseline

| Case | Input | Ghi DB | Trùng | Failed | Quarantine | Ingestion | Throughput |
|---|---:|---:|---:|---:|---:|---:|---:|
| IBM AML-LI 10k | 10,000 | 7,554 | 2,446 | 0 | 0 | 1.161 s | 8,614 rows/s |
| IBM AML-LI 100k | 100,000 | 74,999 | 25,001 | 0 | 0 | 12.808 s | 7,807 rows/s |
| Phase 1 — Hybrid PostgreSQL | 99,997 | n/a | n/a | n/a | n/a | **12.555 s** | **7,965 rows/s** |

Phase 1 là historical ZALOPAY reference, không phải rerun cùng dataset. IBM
100k chậm hơn `0.253 s` (`~2.0%`), chưa cho thấy material regression; so sánh
chỉ mang tính định hướng vì dataset, mapping và worker config khác nhau.

Mốc Phase 1 `4.577 s` là reconciliation, không phải ingestion.

## Experiment đổi batch

Experiment này không thay thế baseline freeze:

| Cấu hình | Ingestion | Throughput | PostgreSQL insert | DB writes |
|---|---:|---:|---:|---:|
| 20k / 1 worker | 12.808 s | 7,807 rows/s | 11.495 s | 7 |
| 100k / 1 worker | **11.080 s** | **9,025 rows/s** | **3.886 s** | **3** |

Batch 100k nhanh hơn `1.728 s` (`13.49%`) và giảm số DB writes. Đây là giảm
batch overhead với một worker, chưa phải fix cho concurrent conflict handling.

## Timing chính

| Stage | 10k / 20k | 100k / 20k | 100k / 100k |
|---|---:|---:|---:|
| Parse | 102.96 ms | 1,142.70 ms | 1,022.69 ms |
| Normalize | 143.07 ms | 1,596.85 ms | 1,379.58 ms |
| Validate | 21.62 ms | 209.48 ms | 188.63 ms |
| PostgreSQL insert | 382.71 ms | 11,495.24 ms | 3,886.07 ms |
| Finalize/update | 4.17 ms | 5.26 ms | 5.27 ms |
| Total `PERF_INGEST` | 1,159.18 ms | 12,806.82 ms | 11,078.31 ms |

`PostgreSQL insert` là write envelope được instrument, không phải một phần có
thể cộng trực tiếp với các stage khác để ra tổng thời gian.

## Finding: deadlock với 2 workers

Cấu hình mặc định `batch_size=20,000`, `write_workers=2` bị PostgreSQL
deadlock tại 40,000 rows sau `4,064.8 ms`. Có `2,275` ingestion keys trùng
giữa các batch; concurrent `ON CONFLICT` có thể tranh chấp trên unique index.

Vì vậy baseline reproducible hiện dùng `write_workers=1`. Đây là guardrail để
đo benchmark, chưa phải performance fix. Chỉ đổi freeze sau khi sửa và
benchmark riêng concurrent conflict handling.

## Cách sử dụng

- Dùng hai case IBM AML-LI 10k và 100k làm Sprint 3 regression baseline.
- Dùng Phase 1 chỉ để tham chiếu định hướng.
- Dùng case batch 100k như experiment về batch overhead.
- Không xem lần chạy 2 workers bị deadlock là benchmark thành công.
