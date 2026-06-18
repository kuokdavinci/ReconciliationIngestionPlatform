# Reconciliation Ingestion Platform — Fintech Priority Roadmap

## 1. Mục tiêu của roadmap này

Roadmap này không nhằm mở rộng thêm nhiều feature mới. Mục tiêu đúng cho repo hiện tại là:

- tăng độ tin cậy của luồng reconciliation;
- làm rõ lineage và auditability;
- siết runtime hygiene để repo nhìn giống một backend fintech có thể vận hành;
- ưu tiên các thay đổi bám sát codebase hiện tại, không dựng thêm kiến trúc quá xa thực tế.

## 2. Đánh giá nhanh hiện trạng

Repo hiện đã có đủ bề mặt cho một bài toán reconciliation tương đối nghiêm túc:

- ingestion pipeline;
- mapping review / approval flow;
- reconciliation API và engine;
- review packet workflow;
- AI insight layer;
- dashboard vận hành;
- MongoDB persistence;
- test suite ở mức khá.

Điểm mạnh là domain fit đã rõ. Điểm yếu hiện tại không nằm ở chỗ thiếu feature, mà nằm ở chỗ một số phần chưa đủ "fintech-grade" về vận hành và kiểm soát:

- runtime/docs chưa đồng bộ;
- validation state chưa thật sự là backend source of truth;
- lineage và audit trail còn mỏng;
- security boundary mới ở mức local/demo;
- một số hardcoded path/local default làm giảm độ tin cậy khi review.

## 3. Những điểm đang lệch ngay trong repo

Các mục dưới đây đã thấy trực tiếp trong codebase và nên được xem là việc thật, không phải giả định:

| Hạng mục | Hiện trạng | Tác động |
|---|---|---|
| Python runtime | `pyproject.toml` và `README.md` ghi `>=3.14`, nhưng `Dockerfile` và `Dockerfile.api` dùng `python:3.11-slim` | Gây mơ hồ môi trường chạy thật |
| Local path hardcode | `src/api/mappings.py` đang dùng `/home/kuokdavinci/AdapterService/scratch/temp_uploads` | Giảm tính portable và khó deploy |
| Docker local default | `docker-compose.yml` đang để `ME_CONFIG_BASICAUTH: "false"` cho `mongo-express` | Ổn cho local, nhưng nên ghi rõ posture hoặc bật auth |
| Validation runtime | Đã có `src/services/runtime_validation.py` và đã trả metadata như `validatedMappingVersion` | Đây là nền tốt để nâng thành backend source of truth thay vì làm entity quá lớn ngay |
| Review flow | Đã có `ReviewDecisionPayload`, `review_packet_actions`, `review packet` APIs | Có thể tận dụng để bổ sung audit trước, chưa cần thay toàn bộ model |

## 4. Nguyên tắc ưu tiên

Thứ tự ưu tiên nên là:

1. Sửa những điểm làm repo mất điểm review ngay lập tức.
2. Tăng khả năng truy vết cho reconciliation run và review decision.
3. Chuẩn hóa validation state ở backend.
4. Bổ sung audit append-only cho hành động quan trọng.
5. Sau cùng mới tách rule engine và siết security sâu hơn.

Không nên làm ngược lại. Nếu chưa sửa runtime/docs/path/CI mà đã thêm nhiều abstraction như `RuleSet`, `AuditEvent`, `ValidationRun` đầy đủ thì repo sẽ nặng thiết kế hơn là giá trị thực.

## 5. Priority roadmap đã tinh chỉnh

### Priority 0 — Khóa phạm vi

Trong ngắn hạn, không nên ưu tiên:

- thêm chatbot/copilot action mới;
- mở thêm màn dashboard;
- thêm workflow AI mới;
- dựng security architecture lớn hơn nhu cầu repo;
- tạo quá nhiều model mới nếu chưa có use case rõ trong code.

Trọng tâm nên là làm cho các flow hiện có đáng tin hơn:

- ingestion;
- mapping approval;
- reconciliation;
- review queue;
- insight generation.

### Priority 1 — Technical hygiene có thể sửa ngay

Đây là nhóm việc có hiệu quả cao nhất trên effort thấp.

#### 1.1. Đồng bộ Python version

Hiện trạng đang lệch giữa:

- [pyproject.toml](/home/kuokdavinci/AdapterService/pyproject.toml:9)
- [README.md](/home/kuokdavinci/AdapterService/README.md:30)
- [Dockerfile](/home/kuokdavinci/AdapterService/Dockerfile:1)
- [Dockerfile.api](/home/kuokdavinci/AdapterService/Dockerfile.api:1)

Khuyến nghị thực tế:

- chốt Python `3.11` hoặc `3.12`;
- sửa `pyproject.toml`, `README.md`, `uv.lock` theo cùng version;
- chỉ nâng Docker image nếu code thật sự phụ thuộc version mới hơn.

`3.14` hiện làm roadmap kém tin cậy hơn vì không khớp runtime container đang dùng.

#### 1.2. Bỏ hardcoded local path

Hiện có hardcoded temp path trong:

- [src/api/mappings.py](/home/kuokdavinci/AdapterService/src/api/mappings.py:522)
- [src/api/mappings.py](/home/kuokdavinci/AdapterService/src/api/mappings.py:678)

Khuyến nghị:

- đưa temp upload dir vào `settings`;
- default về `/tmp/reconciliation_uploads` hoặc thư mục dưới project root có config rõ;
- chỉ giữ các script trong `scripts/tools/` ở dạng local helper, không để chúng ảnh hưởng runtime path của app.

#### 1.3. Format + lint + CI backend tối thiểu

Repo đã có test, nhưng quality gate nên rõ hơn:

- format check;
- lint check;
- pytest.

Nếu chưa muốn mở rộng quá nhiều tool, có thể bắt đầu tối thiểu bằng:

```yaml
- ruff format --check .
- ruff check .
- pytest
```

Mục tiêu ở đây là "mọi PR backend đều có gate nhất quán", không cần biến CI thành quá nặng ngay vòng đầu.

#### 1.4. Ghi rõ security posture local/dev

`mongo-express` đang để không auth trong [docker-compose.yml](/home/kuokdavinci/AdapterService/docker-compose.yml:42). Có hai cách chấp nhận được:

- bật basic auth mặc định;
- hoặc giữ local-only nhưng phải ghi rõ trong README và `docker/README.md`.

Điều quan trọng là người review hiểu đây là local convenience, không phải production default.

### Priority 2 — Nâng lineage nhưng bám vào model hiện có

Đây là chỗ cần tinh chỉnh so với bản roadmap cũ: không nên nhảy ngay sang một mô hình quá lớn nếu repo chưa dùng hết.

Mục tiêu ngắn hạn là mọi reconciliation result và insight đều truy ngược được về lần chạy tạo ra chúng.

#### 2.1. Bổ sung run metadata tối thiểu

Ưu tiên thêm hoặc chuẩn hóa các trường sau cho `ReconciliationRun` / summary persistence:

- `source_file_ids`;
- `mapping_config_id`;
- `mapping_version`;
- `trigger_type`;
- `triggered_by`;
- `started_at`;
- `finished_at`;
- `status`.

Không nhất thiết phải thêm mọi trường từ bản thiết kế cũ ngay vòng đầu. Cần ưu tiên các trường phục vụ:

- review queue;
- operational API;
- AI evidence anchoring.

#### 2.2. Gắn `reconciliation_run_id` vào result và insight path

Trong repo đã có dấu vết dùng `reconciliation_run_id` ở layer analysis cache:

- [src/analysis/cache.py](/home/kuokdavinci/AdapterService/src/analysis/cache.py:119)

Đây là tín hiệu tốt. Hướng phù hợp là:

- chuẩn hóa `reconciliation_run_id` ở persistence/API;
- cho insight sử dụng cùng anchor đó;
- tránh việc mỗi layer tự xây một ID suy diễn khác nhau.

#### 2.3. Index cho các truy vấn lineage thật sự dùng

Chỉ nên tạo index cho các query có ích ngay:

- `reconciliation_run_id`;
- `source_file_id`;
- `reconciliation_status`;
- có thể thêm `mapping_version` nếu UI hoặc report thật sự lọc theo trường này.

Không nên thêm quá nhiều index dự phòng nếu chưa có access pattern rõ.

### Priority 3 — Validation: nâng dần từ runtime metadata lên source of truth

Phần này nên đi theo hướng tiến hóa, không thay máu toàn bộ ngay.

Repo đã có nền ở [src/services/runtime_validation.py](/home/kuokdavinci/AdapterService/src/services/runtime_validation.py:110). Vì vậy lộ trình đúng là:

#### Bước 1

Chuẩn hóa API response để backend trả explicit validation state, ví dụ:

- `NOT_RUN`
- `CURRENT`
- `STALE`
- `FAILED`
- `PASSED_WITH_WARNINGS`

#### Bước 2

Ràng buộc một số action bằng validation state:

- mapping chưa valid thì không activate;
- reconciliation không chạy nếu blocker validation fail;
- review packet hiển thị state từ backend, không tự suy luận ở frontend.

#### Bước 3

Chỉ sau khi state flow đã ổn, mới cân nhắc tách hẳn `ValidationRun` và `ValidationGateResult` thành entity độc lập.

Tinh chỉnh quan trọng ở đây là: `ValidationRun` vẫn là hướng tốt, nhưng không nên là Sprint 1 của phần validation nếu repo hiện vẫn đang ở giai đoạn củng cố vận hành.

### Priority 4 — Audit trail append-only cho action quan trọng

Đây là nâng cấp rất đáng giá vì nó làm repo giống hệ thống tài chính hơn mà không bắt buộc thay đổi toàn bộ business flow.

Nên bắt đầu từ số ít event có giá trị nhất:

- mapping approved;
- mapping rejected;
- mapping activated;
- reconciliation run started/completed/failed;
- review decision submitted.

Khuyến nghị thực tế:

- thêm `AuditEvent` append-only;
- chỉ hỗ trợ `insert` và `read`;
- gắn `actor`, `entity_type`, `entity_id`, `action`, `metadata`, `created_at`.

Không cần ngay từ đầu lưu `before/after` quá chi tiết cho mọi case nếu chưa có dữ liệu ổn định. Có thể bắt đầu bằng metadata vừa đủ, rồi mở rộng dần.

### Priority 5 — Rule engine refactor, nhưng chỉ làm sau khi lineage và audit đã có

Ý tưởng tách rule engine thành các rule versioned là đúng, nhưng đây không phải việc nên làm sớm nhất.

Lý do:

- engine hiện tại đã phục vụ flow đang chạy;
- nếu tách rule quá sớm sẽ tăng abstraction cost;
- khi chưa có run lineage và audit thì versioned rules cũng chưa phát huy hết giá trị.

Hướng phù hợp:

1. xác định các rule đang trộn nhiều logic nhất;
2. tách dần theo cụm nhỏ như `amount`, `status`, `missing-side`;
3. chỉ giới thiệu `rule_version` khi persistence/API đã tiêu thụ được trường này.

Nói ngắn gọn: refactor engine là việc nên làm, nhưng không nên đứng trước validation/audit.

### Priority 6 — Security theo mức đủ dùng cho repo này

Không cần đẩy thẳng lên enterprise IAM. Mức hợp lý hơn là:

- auth cơ bản cho mutating endpoints;
- actor identity cho critical actions;
- role boundary nhẹ cho operator / reviewer / admin;
- non-root container;
- upload validation về size/type/temp cleanup.

Những gì nên làm trước:

1. yêu cầu auth cho endpoint ghi dữ liệu;
2. đưa `reviewed_by` / `triggered_by` / `actor` thành trường bắt buộc hơn ở các action quan trọng;
3. siết upload path và file constraints;
4. sau cùng mới mở rộng JWT hoặc quyền chi tiết hơn.

### Priority 7 — AI insight phải có evidence anchor

Phần AI trong repo nên đi theo hướng hỗ trợ vận hành, không nên là nơi tạo thêm ambiguity.

Điều cần nhất không phải thêm prompt phức tạp, mà là buộc insight bám vào:

- `reconciliation_run_id`;
- mismatch cluster hoặc query scope;
- sample transaction IDs;
- validation warnings liên quan;
- guardrail status.

Nếu phải chọn giữa "thêm insight mới" và "thêm evidence pack rõ ràng", nên chọn vế sau.

## 6. Suggested implementation order

### Sprint 1 — Hygiene và runtime consistency

1. Đồng bộ Python version giữa docs, project config và Docker.
2. Bỏ hardcoded temp upload path.
3. Thêm format/lint/test gate vào CI.
4. Ghi rõ security posture local/dev cho `mongo-express`.

Kết quả mong đợi:

- repo dễ chạy lại hơn;
- reviewer hiểu môi trường thật;
- giảm các lỗi "mất điểm vì bất cẩn".

### Sprint 2 — Lineage tối thiểu cho reconciliation

1. Chuẩn hóa `reconciliation_run_id`.
2. Bổ sung metadata cần thiết cho run/result.
3. Thêm index theo access pattern thực tế.
4. Cho review queue và insights đọc cùng lineage anchor.

Kết quả mong đợi:

- từ insight hoặc result có thể truy ngược về lần chạy tạo ra nó.

### Sprint 3 — Validation state ở backend

1. Chuẩn hóa validation state contract.
2. Chặn activate/run khi validation không đạt.
3. Cập nhật API/UI để không tự đoán state.
4. Chỉ sau đó mới cân nhắc tách `ValidationRun`.

Kết quả mong đợi:

- validation trở thành control point thật, không chỉ là metadata phụ.

### Sprint 4 — Append-only audit

1. Thêm `AuditEvent`.
2. Ghi audit cho mapping approval/rejection/activation.
3. Ghi audit cho reconciliation run lifecycle.
4. Ghi audit cho review decision.

Kết quả mong đợi:

- mọi action quan trọng đều có lịch sử truy vết.

### Sprint 5 — Rule modularization và security hardening

1. Tách dần rule engine theo cụm logic.
2. Thêm `rule_version` khi backend đã sẵn sàng tiêu thụ.
3. Bật auth cho mutating endpoints.
4. Bổ sung actor/role boundary tối thiểu.
5. Chạy container non-root và siết upload handling.

## 7. Final recommendation

Nếu chỉ chọn các việc thật sự đáng làm tiếp theo cho repo này, thứ tự nên là:

1. đồng bộ runtime và docs;
2. bỏ local hardcode;
3. thêm CI gate nhất quán;
4. chuẩn hóa lineage cho reconciliation run;
5. đưa validation state về backend source of truth;
6. thêm append-only audit cho các hành động quan trọng;
7. sau cùng mới refactor rule engine và tăng security boundary.

Kết luận ngắn:

Repo này không cần thêm nhiều feature mới để nhìn "fintech" hơn. Điều nó cần là truy vết tốt hơn, validation rõ hơn, audit rõ hơn, và runtime hygiene sạch hơn.
