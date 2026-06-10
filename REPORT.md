## Báo cáo cập nhật dự án Reconciliation Ingestion Platform

Trong lần cập nhật này, dự án được tái tổ chức lại theo hướng rõ hơn về mặt backend/data pipeline, đồng thời cải thiện dashboard theo hướng tối giản và workflow-driven hơn. Mục tiêu chính là biến hệ thống từ một adapter service xử lý dữ liệu thành một nền tảng ingestion và reconciliation có cấu trúc đầy đủ hơn, có API, dashboard vận hành, approval workflow và AI-assisted insight có kiểm soát.

### 1. Tái tổ chức cấu trúc source code

Codebase được chia rõ hơn theo từng responsibility chính:

* `src/api/`: quản lý FastAPI routers và API surface.
* `src/pipeline/`: xử lý ingestion pipeline.
* `src/reconciliation/`: chứa core reconciliation logic.
* `src/config/`: xử lý mapping config, signature và config health.
* `src/analysis/`: xử lý AI-assisted analysis/insights.
* `src/scheduler/`: xử lý automation jobs.
* `src/validators/`: validate dữ liệu và business rules.
* `src/readers/`, `src/fetchers/`, `src/normalizer/`: tách riêng các bước đọc dữ liệu, lấy dữ liệu và normalize transaction.

Việc tách module giúp code dễ maintain hơn, giảm tình trạng business logic bị trộn giữa API, ingestion, validation và reconciliation.

### 2. Làm rõ luồng ingestion và reconciliation

Luồng xử lý chính được tổ chức lại theo pipeline rõ ràng hơn:

```text
Partner data
→ Fetch/File intake
→ Mapping config loading
→ Parse/Normalize
→ Validate
→ Persist canonical data
→ Run reconciliation
→ Store reconciliation results
→ Expose through API/dashboard
```

Core reconciliation tiếp tục giữ hướng deterministic-first, tức là kết quả đối soát không phụ thuộc vào LLM. AI chỉ đóng vai trò hỗ trợ phân tích insight, tóm tắt anomaly hoặc đề xuất mapping config.

### 3. Củng cố mapping config và approval workflow

Mapping config và review packet được tổ chức rõ hơn thành một lifecycle riêng. Mapping mới hoặc mapping do AI đề xuất không được apply trực tiếp vào runtime, mà cần đi qua bước validation/review trước khi activate.

Luồng này giúp giảm rủi ro trong bài toán tài chính, vì thay đổi mapping có thể ảnh hưởng trực tiếp đến kết quả ingestion và reconciliation.

Các điểm chính:

* Mapping config được load theo partner/workflow/file type.
* Có review packet cho các thay đổi cần duyệt.
* Có action approve/reject/keep current/activate.
* AI-generated mapping chỉ đóng vai trò proposal, không tự động thay đổi runtime behavior nếu chưa được duyệt.

### 4. Mở rộng API surface theo workflow vận hành

Backend API được chia rõ hơn theo các nhóm nghiệp vụ:

* Reconciliation APIs
* Data Explorer APIs
* Mapping APIs
* Review Packet APIs
* Automation APIs
* Copilot/AI Insight APIs
* Operations APIs

Việc này giúp backend không chỉ chạy pipeline nội bộ mà còn expose được các workflow vận hành qua API, phục vụ dashboard và kiểm thử thủ công.

Một số workflow API chính gồm:

* tra cứu kết quả reconciliation
* xem dữ liệu đã ingest
* tạo/validate/approve mapping config
* quản lý review packet
* trigger automation job thủ công
* lấy context/insight cho dashboard hoặc copilot panel

### 5. Tối giản lại giao diện dashboard

Phần frontend/dashboard được điều chỉnh theo hướng tối giản và workflow-driven hơn. Thay vì hiển thị quá nhiều thông tin cùng lúc, dashboard tập trung vào các màn chính theo luồng vận hành:

* Data Intake
* Review Queue
* Reconciliation
* Mapping Studio
* Operations / Command Center

Các thông tin ưu tiên hiển thị là trạng thái, metric chính, verdict ngắn và action tiếp theo. Những phần giải thích dài, evidence hoặc chi tiết review được đưa vào modal/review flow riêng để tránh làm rối màn hình chính.

Ở phần AI insight/review, giao diện được rút gọn để tránh trùng lặp thông tin với insight summary. Mục tiêu là giữ dashboard như một công cụ hỗ trợ operator ra quyết định nhanh, thay vì biến nó thành màn hình log hoặc phân tích quá dày đặc.

### 6. Cải thiện Copilot/AI Insight theo hướng hỗ trợ vận hành

AI layer được đặt ở vai trò hỗ trợ, không thay thế core logic. AI chủ yếu dùng để:

* tạo insight từ metrics hoặc anomaly đã được xử lý trước
* tóm tắt discrepancy patterns
* hỗ trợ đề xuất mapping config
* cung cấp context ngắn cho operator trong dashboard

Core reconciliation vẫn deterministic. Các output từ AI, đặc biệt là mapping proposal, vẫn cần validation/review trước khi được áp dụng.

Hướng này giúp AI có giá trị trong vận hành nhưng không làm mất tính kiểm soát của hệ thống đối soát.

### 7. Cải thiện local development stack

Dự án được tổ chức để dễ chạy local hơn thông qua Docker Compose, với các service chính như:

* MongoDB
* API service
* Scheduler
* SFTP service
* Mongo Express

Ngoài ra, dự án có Makefile và các command hỗ trợ chạy nhanh flow demo/E2E như MOMO flow. Điều này giúp việc kiểm thử end-to-end thuận tiện hơn, thay vì phải chạy từng bước thủ công.

### 8. Tăng độ bao phủ test theo module

Test suite được mở rộng theo nhiều nhóm logic hơn:

* ingestion pipeline
* file readers
* reconciliation core
* API routers
* review packet flow
* automation run-now
* AI analysis/insight orchestration
* seed/tooling cho MOMO E2E

Việc này giúp core flow ingestion → reconciliation → review/approval ổn định hơn, đồng thời giảm rủi ro khi tiếp tục refactor hoặc mở rộng feature.

### 9. Tách tài liệu kỹ thuật khỏi README

Các phần kiến trúc và data flow được tách sang tài liệu riêng như:

* `docs/ARCHITECTURE.md`
* `docs/DATA_FLOW.md`

README tập trung vào phần overview và cách chạy dự án, còn tài liệu trong `docs/` dùng để giải thích sâu hơn về architecture, data flow và operational workflow. Cách tách này giúp codebase dễ review hơn khi mentor hoặc reviewer muốn xem chi tiết kỹ thuật.

### 10. Trạng thái hiện tại của dự án

Sau cập nhật, dự án hiện tập trung vào các core flow chính:

```text
Ingestion
→ Mapping Config
→ Validation
→ Reconciliation
→ Review/Approval
→ API/Dashboard
→ AI-assisted Insight
```

Định hướng hiện tại là ưu tiên ổn định core backend/data workflow trước, sau đó mới mở rộng thêm các phần production concern như authentication/authorization, persistent job queue, audit trail đầy đủ hơn và benchmark với dataset lớn.

### Kết luận

So với phiên bản trước, cập nhật lần này tập trung vào việc làm rõ kiến trúc backend/data pipeline, tách module theo responsibility, củng cố approval workflow cho mapping config, mở rộng API surface, cải thiện test/local development stack và tối giản lại dashboard theo hướng workflow-driven.

Core direction của dự án vẫn giữ nguyên: reconciliation deterministic là trung tâm, AI chỉ đóng vai trò hỗ trợ insight và mapping proposal có kiểm soát. Đây là hướng phù hợp hơn với bài toán đối soát tài chính, vì hệ thống cần đảm bảo tính kiểm chứng được của kết quả thay vì phụ thuộc trực tiếp vào LLM.
