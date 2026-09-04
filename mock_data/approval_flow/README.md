Fixture test cho approval flow.

File:
- `VNPAY_baseline_approved.csv`
  - Khớp với approved config `VNPAY` được seed trong `docker/init-mongo.js`
  - Dùng file này trước nếu `VNPAY` config hiện tại chưa từng được bootstrap `structureSignature`
- `VNPAY_structure_changed_pending_approval.csv`
  - Cùng business data shape nhưng header name khác và thêm một column `Channel`
  - Dùng sau baseline run để trigger proposal `PENDING_APPROVAL`, trong khi approved config hiện tại vẫn là runtime config
- `ACMEPAY_no_approved_config.csv`
  - Dùng với partner `ACMEPAY` để test deterministic blocked path khi chưa có approved config

Thứ tự khuyến nghị:
1. Chạy hoặc upload `VNPAY_baseline_approved.csv` với partner `VNPAY`
2. Sau đó chạy `VNPAY_structure_changed_pending_approval.csv` với partner `VNPAY`
3. Cuối cùng chạy `ACMEPAY_no_approved_config.csv` với partner `ACMEPAY`
