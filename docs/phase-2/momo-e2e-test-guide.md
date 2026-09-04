# MOMO Reconciliation E2E Test & Mocking Guide

Guide này định nghĩa E2E plan an toàn hơn cho **MOMO**, để mock data khớp với
reconciliation logic đang thực sự chạy trong hệ thống.

Quy tắc chính rất đơn giản:

* `Command Center` đọc từ `reconciliation_result`, không đọc trực tiếp từ `internal_transaction`.
* `reconciliation_result` được tạo từ **partner row đã ingest trong ngày** và **internal row ở finalized state** (`SUCCESS`, `FAILED`, `REVERSED`).
* Nếu seed nhiều finalized internal row hơn số row thực tế trong partner file, engine sẽ tạo `MISSING_PARTNER` đúng theo contract.

Vì vậy scenario "green" không được preload finalized internal row không liên
quan cho cùng `partner + date`.

---

## Quick Start

Canonical seed script là [`scripts/demo/sprint1/seed_momo_e2e.py`](../../scripts/demo/sprint1/seed_momo_e2e.py). **Không** dùng legacy `seed_momo_scheduler_green.py`.

### Happy path — các bước chạy lại chính xác

1. Reset Phase 1 data:

```bash
make momo-e2e-reset
```

2. Trigger automation để missing config tạo pending review packet:

```bash
make momo-e2e-run
```

3. Trong UI, mở MOMO packet ở `Review Queue` và approve. Scope kỳ vọng:
   `FULL_SNAPSHOT`

4. Kiểm tra Phase 1 result. Kỳ vọng:
   * `20 MATCHED`
   * `0 MISSING_PARTNER`

5. Chuẩn bị Phase 2 data:

```bash
make momo-e2e-phase2-full
```

`momo-e2e-phase2-full` là incremental happy path chuẩn: giữ approved runtime
mapping và chỉ publish 20 Wave 2 key.

6. Trigger automation lần nữa:

```bash
make momo-e2e-run
```

7. Kiểm tra Phase 2 result. Scope kỳ vọng:
   `INCREMENTAL_APPEND`

   Kỳ vọng:
   * current run chỉ reconcile wave2 key `MOMO_TXN_9100..MOMO_TXN_9119`
   * `20 MATCHED`
   * `0 MISSING_PARTNER`

Với duplicate/review-visibility demo riêng, dùng `make momo-e2e-phase2`. Target
này publish delivery file mới gồm 20 Wave 1 + 10 Wave 2 row và cố ý xóa approved
runtime mapping, nên Run Now tiếp theo sẽ thành `WAITING_REVIEW` và tạo packet
pending mới.

Dùng command này để kiểm tra job sau mỗi run khi cần:

```bash
make momo-e2e-job
```

### Demo file-ingestion failure

Chuẩn bị internal baseline hợp lệ với approved MOMO mapping và partner `.xlsx`
có thể đọc, trong đó row thiếu cả hai source identity column:

```bash
make momo-e2e-fail
```

Command cũng pin approved mapping vào structure của fixture, nên config-health
gate không pause demo để mapping review.

Sau khi đổi backend code, rebuild API và Airflow container một lần:

```bash
make momo-e2e-rebuild
```

Sau đó click `Run Now` trong UI hoặc chạy `make momo-e2e-run`. Schedules view
cần hiển thị runtime `FAILED`, recovery checkpoint `BLOCKED` và đúng
`ingestion_key_error` cùng `BLOCKED` recovery. Thay file bằng file có cả
`msTransId` và `msMaHDon`, rồi dùng `Resolve for retry` với operator reason
trước khi chạy job lại.

### Demo missing-partner

1. Chuẩn bị baseline và anomaly:

```bash
make momo-e2e-reset
make momo-e2e-missing-partner-demo
```

2. Trigger automation:

```bash
make momo-e2e-run
```

3. Trong UI, approve packet và giữ proposed scope là:
   `FULL_SNAPSHOT`

4. Kỳ vọng:
   * `20 MATCHED`
   * `1 MISSING_PARTNER`
   * missing key: `MOMO_TXN_90_MISSING_PARTNER`

### Kiểm tra nhanh

- Nếu thấy `MISSING_PARTNER` row ngoài dự kiến ngay sau `make momo-e2e-reset`, có thể bạn vẫn đang chạy seed flow cũ hoặc approve nhầm packet/file.
- Nếu Phase 2 vẫn hiển thị wave1 row trong current run, kiểm tra packet/file scope là `INCREMENTAL_APPEND`.
- Muốn xem đầy đủ target, chạy `make momo-e2e-help`.

---

## 1. Vấn đề của plan cũ

Plan trước đã seed:

* `40` finalized internal record cho cùng ngày
* nhưng partner file đầu tiên chỉ có `19` row

Thiết lập đó **không** đại diện cho "20/20 reconciled". Nó đại diện cho:

* `19` partner-side rows available for reconciliation
* `21` internal finalized rows with no partner-side match

Vì vậy engine tạo mixed snapshot một cách chính xác, gồm:

* `MATCHED`
* `AMOUNT_MISMATCH`
* `MISSING_PARTNER`

Nếu mục tiêu test là "green dashboard after approval", seed phải khớp chính xác
với nội dung file của phase đó.

---

## 2. E2E mode đúng

Dùng rõ ràng một trong các mode sau, không trộn các mode với nhau.

### Mode A: Green Baseline

Mục tiêu:

* partner file và internal DB đại diện cho cùng một transaction set
* sau approval và reconciliation ngay lập tức, `Command Center` chỉ hiển thị outcome dự kiến của đúng set đó

Quy tắc:

* chỉ seed internal row tồn tại trong partner file hiện tại
* không preload wave tiếp theo vào finalized internal state
* không thêm internal-only anomaly row trừ khi test cần rõ ràng

Kết quả kỳ vọng:

* tổng reconciliation count khớp với file dataset của wave đó

### Mode B: Incremental Wave

Mục tiêu:

* xác minh file thứ hai có thể ingest sau config approval mà không quay lại review

Rules:

* Phase 1: chỉ seed internal row cho Wave 1
* approve config và reconcile Wave 1
* Phase 2: thêm Wave 2 internal row, thay file bằng Wave 2 partner row rồi chạy automation lần nữa
* mỗi wave phải nhất quán nội bộ với file tương ứng

Kết quả kỳ vọng:

* sau mỗi run, reconciliation phản ánh dataset đã seed và được chỉ định hiện tại, không gồm future row không liên quan
* result view chỉ theo batch: Phase 2 chỉ hiện Wave 2 row, còn Phase 1 result vẫn được lưu riêng

### Scope classification rule

Scope được suy ra từ business key, không từ filename. File chỉ chứa key mới là
`INCREMENTAL_APPEND`. File chứa historical key set cùng key mới là
`REPLACEMENT` vì thay thế delivery trước. Nếu overlap evidence thiếu hoặc mâu
thuẫn, packet giữ `UNCONFIRMED` và cần operator chọn.

### Mode C: Intentional Missing Partner

Mục tiêu:

* xác minh finalized transaction chỉ có ở internal trở thành `MISSING_PARTNER`

Rules:

* thêm finalized internal row cố ý không có trong partner file
* ghi rõ các key đó trong scenario

Kết quả kỳ vọng:

* `MISSING_PARTNER` là kết quả dự kiến và phải xuất hiện ở cả `Reconciliation` và `Command Center`

---

## 3. Ground truth rule cho mock data

Các quy tắc này phải đúng với mọi MOMO E2E setup.

1. Partner file key và internal key phải đến từ cùng planned key range.
2. Run "green" không được preload finalized internal key dư cho cùng ngày.
3. Nếu cần mô phỏng future internal record, hãy đưa chúng ra khỏi reconciliation slice hiện tại.
4. `PENDING` internal transaction bị `ReconciliationEngine` bỏ qua ở upstream, nên an toàn khi dùng làm placeholder không tạo `MISSING_PARTNER`.
5. Mọi internal row ở `SUCCESS`, `FAILED` hoặc `REVERSED` đều eligible cho reconciliation trong ngày đó.

---

## 4. Data shape khuyến nghị

### Green Baseline Dataset

Dùng cùng một range chính xác cho cả hai source:

* partner file: `MOMO_TXN_9000` đến `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` đến `MOMO_TXN_9019`

Tùy chọn:

* có thể gồm `1` intentional amount mismatch trong cùng range
* nếu có, tổng kỳ vọng vẫn là `20`, nhưng status breakdown không còn toàn bộ là matched

Không thêm:

* `MOMO_TXN_9100` đến `MOMO_TXN_9119`
* `MOMO_TXN_90_MISSING_PARTNER`

### Incremental Two-Wave Dataset

Wave 1:

* partner file: `MOMO_TXN_9000` đến `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` đến `MOMO_TXN_9019`

Wave 2:

* partner file: `MOMO_TXN_9100` đến `MOMO_TXN_9119`
* internal DB: `MOMO_TXN_9100` đến `MOMO_TXN_9119`

Quan trọng:

* không seed Wave 2 internal row trong Wave 1 nếu test kỳ vọng Wave 1 dashboard sạch

### Intentional Missing Partner Dataset

Base set:

* partner file: `MOMO_TXN_9000` đến `MOMO_TXN_9019`
* internal DB: `MOMO_TXN_9000` đến `MOMO_TXN_9019`

Thêm anomaly:

* chỉ có trong internal DB: `MOMO_TXN_90_MISSING_PARTNER`

Kỳ vọng:

* tổng reconciliation count trở thành `21`
* một row là `MISSING_PARTNER`

---

## 5. Hướng dẫn seed script

Canonical script:

* [scripts/demo/sprint1/seed_momo_e2e.py](../../scripts/demo/sprint1/seed_momo_e2e.py)

Đây là source of truth duy nhất cho MOMO E2E seed data. Script hỗ trợ các mode rõ ràng:

* `reset` — xóa MOMO internal row, seed 20 wave1 row (`MOMO_TXN_9000`..`MOMO_TXN_9019`) và ghi partner xlsx có cùng 20 key. Dùng cho Phase 1 baseline sạch.
* `phase2` — thêm 20 wave2 internal row (`MOMO_TXN_9100`..`MOMO_TXN_9119`) và **overwrite** partner file bằng wave2 key. Kết hợp với `reset`, đây là happy path hai command trong Quick Start.
* `phase2_duplicate` — thêm 10 wave2 internal row mới, publish delivery `*_phase2.xlsx` riêng gồm 20 wave1 cũ + 10 wave2 mới, rồi xóa approved runtime mapping để run kế tiếp đi qua review gate.
* `missing_partner_demo` — insert một internal row `MOMO_TXN_90_MISSING_PARTNER` (50000 VND, `SUCCESS`, cùng ngày) và ghi partner xlsx chỉ có wave1. Ingestion `FULL_SNAPSHOT` tiếp theo tạo đúng `20 MATCHED + 1 MISSING_PARTNER`.

Các `make` target tương ứng (`momo-e2e-reset`, `momo-e2e-phase2-full`, `momo-e2e-phase2`, `momo-e2e-missing-partner-demo`) bọc từng mode và là entrypoint khuyến nghị — xem Quick Start ở trên.

### Legacy script — không dùng

Flow cũ `seed_momo_scheduler_green.py` đã bị xóa. Nếu E2E fixture stale vẫn tham chiếu file này, thay invocation bằng canonical script ở trên.

---

## 6. E2E flow khuyến nghị

### Scenario 1: Config Approval + Clean Reconciliation

Mục tiêu:

* kiểm tra mapping approval flow
* kiểm tra reconciliation ngay sau approval
* kiểm tra `Command Center` total chỉ theo partner file dataset

Kế hoạch:

1. Làm sạch MOMO collection cho target day.
2. Chỉ seed Wave 1 internal row: `MOMO_TXN_9000` đến `MOMO_TXN_9019`.
3. Tạo partner file với cùng Wave 1 key.
4. Chạy automation một lần để missing config tạo pending review packet.
5. Approve config với runtime validation.
6. Để hệ thống re-ingest và reconcile ngay lập tức.
7. Kiểm tra `reconciliation_result.total == 20`.

Kỳ vọng:

* không có `MISSING_PARTNER` ngoài ý muốn từ future-wave row

### Scenario 2: Incremental Second Wave

Mục tiêu:

* kiểm tra approved config được dùng lại mà không qua review

Kế hoạch:

1. Hoàn tất Scenario 1 trước.
2. Chỉ thêm Wave 2 internal row: `MOMO_TXN_9100` đến `MOMO_TXN_9119`.
3. Thay partner file bằng Wave 2 key.
4. Chạy automation lần nữa.
5. Kiểm tra run thứ hai hoàn tất mà không tạo review packet.
6. Kiểm tra reconciliation khớp Wave 2 slice dự kiến.

Kiểm tra khuyến nghị:

* kiểm tra key overlap một cách rõ ràng, không chỉ kiểm tra count

### Scenario 2b: Delivery mới có cùng layout

Mục tiêu:

* kiểm tra source delivery mới không bị ẩn chỉ vì mapping structure giống packet đã approve trước đó

Kế hoạch:

1. Hoàn tất Scenario 1 trước.
2. Run `make momo-e2e-phase2`.
3. Trigger `make momo-e2e-run`.
4. Kiểm tra runtime là `WAITING_REVIEW` và Review Queue có pending packet mới
   cho delivery `*_phase2.xlsx`.

Điều này khác có chủ đích với safe-duplicate path. Packet chỉ được collapse khi
source scope khớp (`rawStageKey`, `backfillRunId` hoặc file identity); chỉ giống
spreadsheet structure không đủ để xác định source identity.

### Scenario 3: Intentional Missing Partner

Mục tiêu:

* kiểm tra discrepancy behavior

Kế hoạch:

1. Seed matched base set.
2. Thêm một số ít finalized internal row.
3. Giữ chúng ngoài partner file.
4. Chạy reconcile.

Kỳ vọng:

* `MISSING_PARTNER` xuất hiện theo thiết kế
* `Command Center` và `Reconciliation` cùng phản ánh các row đó

---

## 7. Verification checklist

Trước khi kết luận một run, kiểm tra cả ba layer:

### Partner-side ingestion

Kiểm tra:

* `reconciliation_file.processingStatus == COMPLETED`
* `data_container` row count cho `partner + date`
* giá trị `partnerData.trace` thực tế đã ingest

### Internal-side eligibility

Kiểm tra:

* `internal_transaction` count cho `partner + date`
* status breakdown của các row đó
* có finalized key dư ngoài partner file range dự kiến hay không

### Reconciliation output

Kiểm tra:

* tổng count của `reconciliation_result`
* status breakdown
* exact key set của `MISSING_PARTNER`

Nếu dashboard hiển thị nhiều record hơn kỳ vọng, việc đầu tiên cần kiểm tra
không phải UI mà là `reconciliation_result` đã có thêm finalized internal-only
key cho ngày đó hay chưa.

---

## 8. Operator command

### Shortcut target

```bash
make momo-e2e-help                # liệt kê MOMO E2E target (Quick Start ở đầu tài liệu)
make momo-e2e-reset               # làm sạch Phase 1 (20 internal row 9000-9019 + partner file)
make momo-e2e-phase2              # partial-duplicate/review demo (20 row cũ + 10 row mới, delivery mới)
make momo-e2e-phase2-full         # Wave 2 happy path chuẩn (20 row mới, dùng lại approved mapping)
make momo-e2e-missing-partner-demo  # thêm MOMO_TXN_90_MISSING_PARTNER cho engine demo
make momo-e2e-run                 # trigger MOMO automation run
make momo-e2e-job                 # kiểm tra MOMO automation job
make momo-e2e-phase2-file         # ghi riêng Wave 2 partner file (9100-9119)
make momo-e2e-rebuild             # rebuild API + Airflow container
```

### Trigger automation run

```bash
curl -s -X POST http://localhost:8000/api/v1/automation/jobs/MOMO/run | jq .
```

### Kiểm tra MOMO automation job

```bash
curl -s http://localhost:8000/api/v1/automation/jobs | jq '.jobs[] | select(.partner == "MOMO")'
```

### Rebuild backend container sau khi đổi logic

```bash
docker compose up -d --build api scheduler
```

---

## 9. Khuyến nghị cuối

Với MOMO E2E, coi "green baseline" và "missing partner demo" là hai fixture khác nhau.

Không dùng một shared seed vừa:

* preloads future-wave finalized rows
* writes only a partial partner file
* but still expects a clean `Command Center`

Fixture đó không nhất quán với reconciliation engine và sẽ tiếp tục tạo total khó hiểu.
