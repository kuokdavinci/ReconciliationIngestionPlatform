# Đánh Giá A/B: Baseline vs Optimized

Ngày: 2026-06-16  
Mục tiêu: so sánh ngắn gọn giữa `baseline` và `optimized` cho các phần quan trọng của luồng đối soát

## 1. Tóm tắt điều hành

| Hạng mục | Dataset | Baseline | Optimized | Chênh lệch | Kết luận |
| --- | --- | ---: | ---: | ---: | --- |
| Results page 1 | `100k` | `1.0412s` | `0.0545s` | nhanh hơn `19.1x` | Tối ưu rất rõ |
| Summary insight prep | `100k` | `3.1334s` | `0.2709s` | nhanh hơn `11.6x` | Tối ưu rất rõ |
| Discrepancy insight prep | `100k` | `2.9733s - 3.0886s` | `0.2592s - 0.2883s` | nhanh hơn `10.6x - 11.8x` | Tối ưu rất rõ |
| Reconcile engine full | `100k` | `6.9447s` | `8.1372s` | baseline nhanh hơn `1.17x` | `100k` chưa đủ lớn để tối ưu engine thắng |
| Results page 1 | `1M` | `11.4394s` | `0.4792s` | nhanh hơn `23.9x` | Tối ưu rất rõ |
| Summary insight prep | `1M` | `35.1928s` | `2.3620s` | nhanh hơn `14.9x` | Tối ưu rất rõ |
| Discrepancy insight prep | `1M` | `33.9939s` | `2.4946s` | nhanh hơn `13.6x` | Tối ưu rất rõ |
| Reconcile engine full | `1M` | `153.270s` | `97.893s` | nhanh hơn `1.57x` | `1M` bắt đầu thấy rõ giá trị của tối ưu engine |

## 2. So sánh query và insight prep

### 2.1 Dataset `100k`

| Hạng mục | Baseline | Optimized | Chênh lệch tuyệt đối | Tỷ lệ |
| --- | ---: | ---: | ---: | ---: |
| Results page 1 (`25` dòng) | `1.0412s` | `0.0545s` | `0.9867s` | `19.1x` |
| Summary insight prep | `3.1334s` | `0.2709s` | `2.8625s` | `11.6x` |
| Discrepancy prep | `2.9733s - 3.0886s` | `0.2592s - 0.2883s` | `2.71s - 2.83s` | `10.6x - 11.8x` |

| Tổng hợp `100k` | Baseline | Optimized | Chênh lệch | Tỷ lệ |
| --- | ---: | ---: | ---: | ---: |
| Tổng thời gian query + insight prep | `13.3035s` | `1.1348s` | `12.1687s` | `11.7x` |

### 2.2 Dataset `1M`

| Hạng mục | Baseline | Optimized | Chênh lệch tuyệt đối | Tỷ lệ |
| --- | ---: | ---: | ---: | ---: |
| Results page 1 (`25` dòng) | `11.4394s` | `0.4792s` | `10.9602s` | `23.9x` |
| Summary insight prep | `35.1928s` | `2.3620s` | `32.8308s` | `14.9x` |
| Discrepancy prep | `33.9939s` | `2.4946s` | `31.4993s` | `13.6x` |

| Tổng hợp `1M` | Baseline | Optimized | Chênh lệch | Tỷ lệ |
| --- | ---: | ---: | ---: | ---: |
| Tổng thời gian query + insight prep | `80.6261s` | `5.3358s` | `75.2903s` | `15.1x` |

### 2.3 Khác biệt về lượng dữ liệu phải xử lý

| Luồng | Dataset | Baseline | Optimized |
| --- | --- | ---: | ---: |
| Results page | `100k` | load full `100.000` rồi mới slice | chỉ trả `25` dòng |
| Summary insight prep | `100k` | quét full `100.000` rows | aggregate DB ra `5` grouped statuses |
| Discrepancy prep | `100k` | quét full `100.000` rows | chỉ lấy `151` sampled error rows |
| Results page | `1M` | load full `1.000.000` rồi mới slice | chỉ trả `25` dòng |
| Summary insight prep | `1M` | quét full `1.000.000` rows | aggregate DB ra `5` grouped statuses |
| Discrepancy prep | `1M` | quét full `1.000.000` rows | chỉ lấy `160` sampled error rows |

## 3. So sánh reconcile engine

### 3.1 Dataset `100k`

| Chỉ số | Baseline | Optimized | Kết luận |
| --- | ---: | ---: | --- |
| Reconcile full | `6.9447s` | `8.1372s` | baseline nhanh hơn nhẹ |
| Inserted rows | `100.050` | `100.050` | output tương đương |
| Internal index size | `85.613` | `85.613` | cùng tập internal finalized |

### 3.2 Dataset `1M`

| Chỉ số | Baseline | Optimized | Chênh lệch | Kết luận |
| --- | ---: | ---: | ---: | --- |
| Reconcile full | `153.270s` | `97.893s` | tiết kiệm `55.377s` | optimized thắng rõ |
| Throughput xấp xỉ | `~6.524 rows/s` | `~10.215 rows/s` | tăng `~3.691 rows/s` | scale tốt hơn rõ rệt |
| Inserted rows | `1.000.000` | `1.000.000` | bằng nhau | output tương đương |
| Internal index size | `855.630` | `855.630` | bằng nhau | cùng tập internal finalized |

## 4. Số liệu dataset benchmark

### 4.1 Dataset `100k`

| Thuộc tính | Giá trị |
| --- | --- |
| Partner | `VNPAY` |
| Date | `2026-06-15` |
| Quy mô | `100.000 reconciliation_result rows` |
| Sample discrepancy dùng cho prep | `151` rows |

### 4.2 Dataset `1M`

| Thuộc tính | Giá trị |
| --- | --- |
| Partner | `VNPAY_1M_BENCH` |
| Date | `2026-06-16` |
| Partner rows | `1.000.000` |
| Internal rows | `855.630` |
| Sample discrepancy dùng cho prep | `160` rows |

### 4.3 Phân bố trạng thái `1M`

| Status | Count |
| --- | ---: |
| `MATCHED` | `70` |
| `STATUS_MISMATCH` | `10` |
| `MISSING_INTERNAL` | `144.370` |
| `AMOUNT_MISMATCH` | `658.660` |
| `MULTIPLE_MISMATCH` | `196.890` |

## 5. Kết luận cuối

| Chủ đề | Kết luận |
| --- | --- |
| Results / insight prep | Tối ưu có hiệu quả rất rõ ở cả `100k` và `1M` |
| Engine ở `100k` | Chưa thấy lợi ích, baseline còn nhanh hơn nhẹ |
| Engine ở `1M` | Tối ưu bắt đầu phát huy rõ, tiết kiệm hơn `55s` |
| Điểm chậm còn lại trong UI | Chủ yếu là `LLM inference`, không còn là `results` hay local prep path |

## 6. Khuyến nghị tiếp theo

| Ưu tiên | Việc nên làm | Lý do |
| --- | --- | --- |
| Cao | Cache + prewarm `anomalies` insight | nhắm đúng phần còn chậm người dùng đang thấy |
| Trung bình | Chỉ benchmark `1M` bổ sung nếu cần production-flow thật | hiện đã có đủ số để kết luận về query/prep và engine |
