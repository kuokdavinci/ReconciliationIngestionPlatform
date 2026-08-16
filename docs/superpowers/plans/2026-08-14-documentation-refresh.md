# Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đồng bộ README và tài liệu vận hành/kiến trúc với repository hiện tại, đồng thời hợp nhất Sprint 2.5 và 2.6 thành một Sprint 2.5 duy nhất.

**Architecture:** Giữ các report/runbook chi tiết làm evidence, nhưng tạo một lớp tài liệu canonical ngắn gồm README, chỉ mục docs, architecture/module/configuration/CI/milestone. Phase 2 có index riêng liệt kê đầy đủ từng sprint; Sprint 2.5 mô tả cả Airflow integration và recovery hardening.

**Tech Stack:** Markdown, Mermaid, FastAPI, Python 3.11, Airflow 3.3, Next.js 16, PostgreSQL 16, MongoDB 7, Docker Compose, CodeGraph.

## Global Constraints

- Không thay đổi code runtime, test, schema, Docker Compose hoặc cấu hình ứng dụng.
- Bám theo `.codegraph/codegraph.db` hiện tại và các file cấu hình/CI thực tế.
- Không xoá các tài liệu evidence chi tiết của sprint; chỉ cập nhật liên kết, tiêu đề hoặc trạng thái khi cần.
- Sprint 2.6 không còn là sprint độc lập trong navigation; toàn bộ nội dung của nó được quy về Sprint 2.5 — Airflow integration & recovery hardening.
- Giữ các thay đổi đang có trong working tree của người dùng ngoài phạm vi tài liệu được chọn.

---

### Task 1: Tạo bộ chỉ mục tài liệu canonical

**Files:**
- Create: `docs/phase-2/INDEX.md`
- Modify: `docs/INDEX.md`

- [ ] **Step 1: Liệt kê đầy đủ Phase 1 và Phase 2 theo tài liệu đang tồn tại.**

  Phase 2 phải có các mục riêng cho Sprint 1, Sprint 2, Sprint 2.5 hợp nhất, Sprint 3 và Sprint 4; Sprint 2.6 chỉ xuất hiện như tài liệu hardening thuộc Sprint 2.5.

- [ ] **Step 2: Ghi rõ scope và trạng thái của Sprint 2.5 hợp nhất.**

  Mục Sprint 2.5 phải liên kết migration runbook và recovery hardening report, đồng thời nêu Airflow là control plane duy nhất trong manual pilot.

- [ ] **Step 3: Đặt `docs/phase-2/INDEX.md` làm index con được link từ `docs/INDEX.md`.**

  Kiểm tra mọi đường dẫn tương đối trỏ đến file đang có trong repository.

---

### Task 2: Viết lại README theo runtime hiện tại

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Cập nhật mô tả, kiến trúc và layout theo codegraph.**

  Phản ánh `src/api`, `src/application`, `src/domain`, `src/infrastructure`, `src/pipeline`, `src/fetchers`, `src/reconciliation`, `src/analysis`, `dags/` và `frontend-next/`; không ghi các namespace đã bị xoá như `src/scheduler/` hay `src/services/`.

- [ ] **Step 2: Giữ quick start có thể chạy được.**

  Bao gồm `uv sync --all-extras --dev`, `.env`, Compose dependencies, Alembic, API, Airflow pilot và dashboard; ghi rõ cổng mặc định và `httpx2` workaround của test client.

- [ ] **Step 3: Rút gọn nhưng đủ các nhóm cấu hình, lệnh demo, test/CI và API surface.**

  Link tới docs canonical thay vì lặp lại toàn bộ runbook chi tiết.

- [ ] **Step 4: Ghi trạng thái milestone.**

  Sprint 2.5 là mục hợp nhất Airflow + recovery hardening; live acceptance/deployment evidence vẫn được phân biệt với automated verification.

---

### Task 3: Đồng bộ architecture, module và configuration docs

**Files:**
- Modify: `docs/phase-1/ARCHITECTURE.md`
- Modify: `docs/phase-1/MODULES.md`
- Modify: `docs/phase-1/CONFIGURATION.md`

- [ ] **Step 1: Mô tả đúng application boundaries và data flow hiện tại.**

  Nêu application services, domain contracts, infrastructure adapters, ingestion pipeline, Airflow DAG, dual persistence và active Next.js dashboard.

- [ ] **Step 2: Cập nhật module map và API router groups.**

  Dùng các router/prefix thực tế trong `src/api/` và module path hiện có trong codegraph; loại các tham chiếu legacy không còn tồn tại.

- [ ] **Step 3: Cập nhật bảng configuration theo `src/config/settings.py`, `src/analysis/config.py`, `.env.example` và Compose.**

  Tách nhóm APP, Airflow, database/SFTP, ingestion/reconciliation tuning và AI; nhấn mạnh secret local không dùng cho production.

---

### Task 4: Đồng bộ CI, milestone và known issues

**Files:**
- Modify: `docs/CI-MAP.md`
- Modify: `docs/MILESTONES.md`
- Modify: `docs/KNOWN_ISSUES.md`
- Modify: `docs/phase-2/sprint-2.6-recovery-hardening.md`

- [ ] **Step 1: Sửa CI map theo workflow thực tế.**

  Cập nhật source scope `src/application/automation` và loại đường dẫn `src/scheduler`/`src/services` nếu không còn trong index; giữ đúng lệnh Backend, Ingestion, Eval và Frontend CI.

- [ ] **Step 2: Cập nhật milestone/status.**

  Thay trạng thái “planning chưa bắt đầu” bằng trạng thái đã có implementation/evidence tương ứng; phân biệt automated verification, local pilot và live acceptance.

- [ ] **Step 3: Sửa known issues để không phủ định dashboard/AI đã tồn tại.**

  Giữ các ràng buộc môi trường và follow-up thật sự còn mở, bỏ các scope statement lỗi thời.

- [ ] **Step 4: Đổi tiêu đề và cross-reference Sprint 2.6 thành phần hardening của Sprint 2.5.**

  Giữ lịch sử nội dung và evidence, nhưng không để navigation hiểu đây là sprint thứ sáu độc lập.

---

### Task 5: Kiểm chứng tài liệu

**Files:**
- Test: `README.md`, `docs/**/*.md`, `.codegraph/codegraph.db`

- [ ] **Step 1: Kiểm tra liên kết nội bộ và file đích.**

  Dùng script/read-only shell để tìm markdown links và xác nhận các path tương đối tồn tại.

- [ ] **Step 2: Quét drift namespace và sprint naming.**

  Xác nhận không còn tham chiếu canonical tới `src/scheduler/`, `src/services/`, `frontend/` hoặc “Sprint 2.6” như sprint độc lập; cho phép các historical notes cần thiết trong evidence.

- [ ] **Step 3: Chạy kiểm tra định dạng và diff.**

  Chạy `rtk git diff --check`, `rtk codegraph status` và review `git diff -- README.md docs` để bảo đảm chỉ thay đổi tài liệu trong phạm vi.

**Done when:** README chạy đúng theo cấu hình hiện tại, docs index liệt kê đầy đủ mọi sprint Phase 2 với Sprint 2.5 hợp nhất Airflow + recovery hardening, các docs kiến trúc/CI/status không còn drift chính đã phát hiện, và mọi kiểm tra tài liệu đều pass.
