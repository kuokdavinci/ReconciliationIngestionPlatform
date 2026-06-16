# Benchmark Luồng Đối Soát

Ngày: 2026-06-15  
Môi trường: Docker local  
Dataset: `VNPAY / 2026-06-15 / 100.000 dòng reconciliation_result`  
Runtime run gần nhất: `COMPLETED`  
File gần nhất: `VNPAY_2026-06-15.xlsx`

## Phạm vi đo

Benchmark này đánh giá luồng operator hiện tại sau các thay đổi về runtime visibility và pagination:

1. `Run Now` / hiển thị trạng thái intake partner
2. Tải kết quả đối soát ở tab `Reconciliation`
3. Tải AI insight cho `anomalies`, `patterns`, và `recommendations`

## Bảng benchmark

| Khu vực | Endpoint / Action | Phạm vi dữ liệu | Kích thước phản hồi | Độ trễ (s) | Nhận xét |
| --- | --- | --- | ---: | ---: | --- |
| Bảng Automation | `GET /api/v1/automation/jobs` | tất cả partner | 3448 B | 0.0063 | Đủ nhẹ để poll thường xuyên |
| Trạng thái run | `GET /api/v1/reconciliation/run-status?partner=VNPAY&date=2026-06-15` | 1 partner/date | 550 B | 0.0057 | Đủ nhẹ cho realtime status |
| Review records | `GET /api/v1/reconciliation/review-records?partner=VNPAY&date=2026-06-15` | 1 partner/date | 14 B | 0.0025 | Gần như không đáng kể |
| Trang kết quả | `GET /api/v1/reconciliation/results?partner=VNPAY&date=2026-06-15&limit=25&offset=0` | page đầu, 25 dòng | 12333 B | 0.0761 | Tốt sau khi chuyển sang DB pagination |
| Stats | `GET /api/v1/reconciliation/stats?partner=VNPAY&date=2026-06-15` | số liệu tổng hợp | 251 B | 0.1502 | Chấp nhận được |
| Insight: anomalies | `GET /api/v1/reconciliation/insights?type=anomalies&partner=VNPAY&date=2026-06-15` | aggregate + selected error signals | 2123 B | 9.1227 | Điểm nghẽn lớn nhất hiện tại |
| Insight: patterns | `GET /api/v1/reconciliation/insights?type=patterns&partner=VNPAY&date=2026-06-15` | aggregate + selected error signals | 2325 B | 9.1139 | Điểm nghẽn lớn nhất hiện tại |
| Insight: recommendations | `GET /api/v1/reconciliation/insights?type=recommendations&partner=VNPAY&date=2026-06-15` | aggregate + selected error signals | 778 B | 6.1439 | Vẫn chậm, nhưng thấp hơn anomalies/patterns |

## Đánh giá

| Phần luồng | Trạng thái | Đánh giá |
| --- | --- | --- |
| Hiển thị runtime partner data | Tốt | `Automation` polling và unified runtime run đủ nhanh để hiển thị realtime cho operator. |
| Tải bảng kết quả đối soát | Tốt | DB pagination và page size mặc định `25` đã giảm rõ phần payload nằm trên critical path. |
| Tải reconciliation stats | Tốt | Aggregate stats đủ nhẹ để nằm trong luồng tải ban đầu. |
| AI insights | Cần tối ưu thêm | Dù đã giới hạn đầu vào còn aggregate + selected error signals, insight vẫn là phần chậm nhất. |

## Phát hiện chính

1. Điểm nghẽn UX chính không còn là `results`, mà là luồng AI insight.
2. Tab `Reconciliation` hiện đã mượt hơn rõ vì:
   - `results` được phân trang ở DB
   - page đầu chỉ lấy `25` dòng
   - `results`, `stats`, và `run status` có thể hiện trước khi AI insight xong
3. Endpoint của `Automation` và `run-status` đủ nhẹ để poll mà chưa tạo áp lực đáng kể lên backend.

## Quick win còn đáng làm

| Ưu tiên | Quick win | Tác động kỳ vọng |
| --- | --- | --- |
| Cao | Cache AI insight mạnh hơn theo `partner/date/type` sau khi reconcile xong | Giảm việc phải chờ lại `6-9s` khi operator mở lại cùng một tab insight |
| Cao | Prewarm riêng tab `anomalies` ngay sau khi reconcile hoàn tất | Làm insight được dùng nhiều nhất hiển thị nhanh hơn mà không phải eager-load mọi tab |
| Trung bình | Giảm thêm kích thước sample lỗi nếu chất lượng insight vẫn chấp nhận được | Có thể hạ thêm latency LLM với rủi ro sản phẩm thấp |
| Trung bình | Giữ loading/empty/error state riêng cho từng insight block | Đã làm một phần ở frontend; tiếp tục giữ AI delay không chặn dữ liệu core |
| Thấp | Thêm timestamp kiểu `insight generated at` | Giúp operator hiểu insight đang là cache hay vừa được sinh mới |

## Khuyến nghị hiện tại

Trong phạm vi công việc hôm nay, bước tiếp theo có giá trị nhất mà chưa cần refactor lớn là:

`cache + prewarm tab anomalies, trong khi vẫn giữ results/stats/run-status là bề mặt realtime chính`

Hướng này vẫn thực dụng:

- không thêm hạ tầng mới
- không đổi semantics của reconcile
- cải thiện đúng phần operator đang phải chờ nhiều nhất
