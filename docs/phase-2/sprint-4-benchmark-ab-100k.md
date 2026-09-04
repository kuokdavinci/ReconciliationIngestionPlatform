# Sprint 4 — A/B benchmark: Fraud Detection 100k

**Trạng thái:** `completed — no winner`

- Dataset SHA-256: `e3895c988fe37efc76dabfe62d23f7ab75e89477bb17ba0c53092b008431caf6`
- Boundary: `IngestionPipeline.process_file`.
- PostgreSQL persistence: `LOGGED`; không đổi schema/index.

| Variant | Median ms | MAD ms | RSS max | Hợp lệ | Promote |
|---|---:|---:|---:|---|---|
| `control-20k-w1` | 11599.917 | 210.602 | 243965952 | True | False |
| `current-20k-w2` | 11346.105 | 36.118 | 387424256 | True | False |
| `small-10k-w2` | 11114.679 | 96.406 | 244736000 | True | False |
| `large-40k-w2` | 11226.138 | 78.237 | 674660352 | True | False |
| `large-80k-w2` | 11663.689 | 172.196 | 819974144 | True | False |
| `fast-20k-w2` | 10184.576 | 84.044 | 297930752 | True | False |

**Decision:** không promote variant nào. `fast_mode=true` chỉ diagnostic-only;
full MOMO validation được tách khỏi latency ranking và chỉ chạy sau một winner
`fast_mode=false` hợp lệ.
