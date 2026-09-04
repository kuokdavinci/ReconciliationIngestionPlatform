# Sprint 4 — Performance decision

**Trạng thái:** `completed — baseline retained`

SQL profile, candidate review và A/B benchmark đã hoàn tất. Không có candidate
nào đủ điều kiện promote; production defaults giữ nguyên.

## SQL và candidate review

- SQL profile được sinh tại `data/eda/fraud_detection/profiles/benchmark_sql_profile_100k.json`;
  đây là artifact local và được ignore khỏi repository.
- Không rewrite SQL khi chưa có bottleneck an toàn từ EXPLAIN.
- Candidate `stream-copy-generator` hợp lệ về correctness nhưng không đạt
  optimization gate: wall-clock median/MAD `13570.957/641.711 ms`, peak RSS
  median/max `229556224/230137856 bytes`.

## A/B decision

| Variant | Median ms | MAD ms | RSS max | Valid | Promote |
|---|---:|---:|---:|---|---|
| `control-20k-w1` | 11928.661 | 345.709 | 230612992 | True | False |
| `current-20k-w2` | 10703.181 | 153.013 | 360980480 | True | False |
| `small-10k-w2` | 10142.153 | 207.320 | 231063552 | True | False |
| `large-40k-w2` | 10354.490 | 180.375 | 624783360 | True | False |
| `large-80k-w2` | 10647.783 | 107.549 | 757981184 | True | False |
| `fast-20k-w2` | 9286.087 | 73.893 | 272154624 | True | False |

- Winner: `none`; memory gate chặn promotion.
- `fast_mode=true` chỉ diagnostic-only.
- Full MOMO validation chỉ chạy sau khi có winner `fast_mode=false` hợp lệ.
