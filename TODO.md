## UI

### review packet
- [x] preview sample step 3 cần gọn lại
- [x] internal db không ghi nhận đúng thông tin khi mở review packet của backfill scenario
### Schedule run status
- [x] kẹt 2 state running và watting review
- [x] chọn option action chưa tối ưu
- [x] không cập nhật state của các run trong schedule khi chuyển state.
### Runtime detail 
- [x] event timeline chưa trực quan, cần visualize, chữ đỏ không phù hợp(chỉ dùng khi biểu diễn lỗi)

## flow
- [x] chưa có luồng chạy backfill trong review packet (luồng chưa phù hợp)

### Verification

- Backend regression: `34 passed` across automation, review architecture, stream execution, backfill and Airflow backfill tests.
- Frontend quality: lint, typecheck and production build pass; targeted Playwright coverage passes for review preview, recovery, waiting review, out-of-order schedule polling and VNPAY backfill.
- Backfill review packets now carry `backfillRunId` and are scoped to the parent business date before approval/resume.
