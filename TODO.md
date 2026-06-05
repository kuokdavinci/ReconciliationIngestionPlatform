# TODO List

- [ ] **Kiểm tra lại cơ chế tính độ tin cậy đối soát (Confidence Calculation)**:
  - Cần đánh giá kỹ lưỡng các hệ số tin cậy (như `0.8` và `0.88`) dựa trên tên file và sự tồn tại của các file cùng ngày trong hàm `classify_scope` thuộc file `src/reconciliation/scope.py`.

- [ ] **Cải tiến giao diện card Intake sau khi filedrop (Hiển thị Timestamp)**:
  - Thêm hiển thị thời gian nạp file (`timestamp` / `uploadedAt`) dưới tiêu đề của mỗi file trong các thẻ danh sách **Incoming Files** và **Blocked Or Failed** ở giao diện Data Intake.
