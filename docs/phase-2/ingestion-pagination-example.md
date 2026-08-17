# Ví dụ pagination, replay và failure/resume

Tài liệu này là trace ngắn để mentor đi từ API fetch đến checkpoint recovery.

## Luồng thành công theo từng trang

`APIFetcher` tạo một source unit cho mỗi response:

| Trang | `cursorBefore` | `cursorAfter` | Ý nghĩa |
|---|---|---|---|
| 1 | `null` | `cursor-1` | Bắt đầu stream |
| 2 | `cursor-1` | `cursor-2` | Tiếp tục từ boundary của trang 1 |
| 3 | `cursor-2` | `null` | Terminal page |

Mỗi unit có `sourceUnitKey`, `cursorBefore`, `cursorAfter`, `localPath` và
`sourceIdentity`. Checkpoint dùng `sourceUnitKey` làm identity để không xử lý
lại một page đã hoàn thành.

## Failure và resume

Ví dụ deterministic nằm trong
[`scripts/demo/sprint2/fixture.py`](../../scripts/demo/sprint2/fixture.py) và
được kiểm tra bởi các stream/pagination regression tests hiện tại:

1. Page 1 hoàn thành, checkpoint lưu `lastCompletedUnitKey=page:1` và
   `cursorAfter=cursor-1`.
2. Page 2 thất bại có kiểm soát; stream dừng, không nhảy sang page 3.
3. Lần chạy sau lấy các unit sau checkpoint, resume từ page 2 với
   `cursorBefore=cursor-1`.
4. Replay page cuối chỉ được tính là replay, không tạo thêm logical unit.
5. Fixture từ chối cursor sai, nên boundary bị lệch sẽ fail rõ ràng thay vì
   âm thầm bỏ sót dữ liệu.

Chạy trace:

```bash
uv run python scripts/demo/sprint2/run.py
uv run pytest -q tests/test_api_pagination.py tests/test_stream_runner.py
```

Contract HTTP pagination được kiểm tra riêng trong
[`tests/test_api_pagination.py`](../../tests/test_api_pagination.py), bao gồm
cursor tiếp theo, terminal cursor rỗng, single-unit resume và lỗi parse response.
