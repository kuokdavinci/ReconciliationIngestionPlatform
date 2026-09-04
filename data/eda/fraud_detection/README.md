# Fraud Detection Dataset — EDA Sprint 3

Thư mục này chứa dataset local canonical và các profile output có thể tái lập
cho Workstream A của Sprint 3.

| Thư mục | Mục đích | Git policy |
|---|---|---|
| `raw/` | CSV local gốc dùng cho Kaggle notebook/profile | Ignored |
| `interim/` | Slice tạm hoặc analysis input có kiểm soát | Ignored |
| `profiles/` | Profile output cho machine và human | Tracked |
| `manifest.yaml` | Metadata về provenance và checksum | Tracked |

Raw file được giữ local có chủ đích. Exploratory notebook vẫn là artefact chỉ
dùng trên Kaggle; profile script trong repository là evidence source có thể tái
lập cho Workstream A.

Dataset public/synthetic này chỉ phù hợp cho EDA và ingestion quality
profiling. Đây không phải production settlement source. Hãy kiểm tra source
license trước khi redistribution.
