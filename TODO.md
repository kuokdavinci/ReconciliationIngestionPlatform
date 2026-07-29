1. Mục tiêu
 
Hoàn thiện pipeline hiện tại theo bốn khía cạnh:
 
Idempotency: Chạy lại hoặc retry không tạo dữ liệu trùng.
Incremental processing và recovery: Chỉ xử lý dữ liệu mới theo đặc tính của từng nguồn và có thể tiếp tục an toàn khi xảy ra lỗi.
Data quality: Bản ghi không hợp lệ được lưu, truy vết và xử lý lại.
Observability: Theo dõi được trạng thái, số lượng dữ liệu và điểm lỗi của từng lần chạy.
 
2. Các vấn đề cần giải quyết, phương pháp và tiêu chí đánh giá
 
Sub-problem 1 — Làm thế nào để pipeline có thể chạy lại mà không tạo dữ liệu trùng?
 
Hiện trạng:
Hệ thống đã có khả năng phát hiện file được gửi lại, nhưng chưa bao quát đầy đủ trường hợp API bị retry, một phần dữ liệu được lấy lại hoặc cùng một giao dịch xuất hiện trong nhiều lần xử lý.
 
Phương pháp thực hiện:
 
Thiết lập cơ chế nhận diện dữ liệu đã xử lý ở ba cấp độ: file, lần lấy dữ liệu từ API và bản ghi giao dịch.
Với file, nhận diện theo nội dung thay vì chỉ dựa trên tên file.
Với API, nhận diện đơn vị dữ liệu đã lấy như page, cursor hoặc khoảng truy vấn.
Với giao dịch, ưu tiên định danh ổn định do partner cung cấp; nếu không có, sử dụng khóa nghiệp vụ được xác định riêng theo từng partner.
Áp dụng ràng buộc chống trùng hoặc cơ chế upsert tại tầng lưu trữ.
 
Tiêu chí đánh giá:
 
Chạy lại cùng file hoặc cùng dữ liệu API không làm tăng số bản ghi đã lưu.
Một giao dịch xuất hiện lại trong nhiều lần xử lý không tạo duplicate.
Chạy lại sau partial failure cho kết quả cuối giống một lần chạy thành công từ đầu.
Các giao dịch hợp lệ có dữ liệu gần giống nhau không bị nhận diện nhầm là trùng.
 
 
Sub-problem 2 — Làm thế nào để chỉ xử lý dữ liệu mới và không bỏ sót dữ liệu khi pipeline gặp lỗi?
 
Hiện trạng:
Pipeline có thể lấy dữ liệu theo lịch nhưng chưa quản lý đầy đủ tiến độ xử lý thành công theo từng loại nguồn.
 
Phương pháp thực hiện:
 
Quản lý tiến độ xử lý theo đơn vị phù hợp với từng nguồn:
 
API: lưu cursor, page token, thời điểm cập nhật hoặc khoảng truy vấn cuối cùng đã xử lý thành công.
SFTP và file drop: theo dõi trạng thái từng file dựa trên nội dung file và chỉ xử lý file mới hoặc file chưa hoàn tất.
Chỉ xác nhận một page, khoảng dữ liệu hoặc file đã hoàn thành sau khi dữ liệu được lưu thành công.
Khi xảy ra lỗi, chạy lại đơn vị chưa hoàn tất và kết hợp với idempotency để không tạo dữ liệu trùng.
Backfill được chạy theo partner và khoảng thời gian riêng, không làm thay đổi tiến độ của luồng định kỳ.
 
Tiêu chí đánh giá:
 
API chỉ lấy dữ liệu sau vị trí cuối cùng đã hoàn tất.
SFTP và file drop chỉ xử lý file mới hoặc file chưa hoàn tất.
File đã hoàn tất không bị xử lý lại khi scheduler quét lại thư mục.
Lỗi giữa một API page hoặc trong quá trình xử lý file không làm đơn vị dữ liệu bị đánh dấu hoàn tất.
Sau khi retry, pipeline không bỏ sót và không tạo thêm dữ liệu trùng.
Backfill không làm thay đổi tiến độ của luồng định kỳ.
 
 
Sub-problem 3 — Làm thế nào để không làm mất các bản ghi không hợp lệ?
 
Hiện trạng:
Pipeline có thể phát hiện lỗi trong quá trình đọc, chuẩn hóa và kiểm tra dữ liệu, nhưng các bản ghi lỗi chưa có quy trình lưu trữ và xử lý lại thống nhất.
 
Phương pháp thực hiện:
 
Phân loại lỗi theo mức độ ảnh hưởng.
Lỗi cấu trúc nghiêm trọng hoặc thiếu dữ liệu bắt buộc sẽ dừng toàn bộ batch.
Lỗi chỉ ảnh hưởng một số bản ghi sẽ không làm dừng batch; các bản ghi hợp lệ vẫn tiếp tục được xử lý.
Lưu bản ghi lỗi vào khu vực quarantine cùng dữ liệu nguồn, vị trí trong nguồn, loại lỗi, nguyên nhân và phiên bản cấu hình đã sử dụng.
Cho phép xử lý lại dữ liệu lỗi sau khi dữ liệu hoặc cấu hình mapping được điều chỉnh.
 
Tiêu chí đánh giá:
 
Mọi bản ghi bị reject đều được lưu có cấu trúc và không chỉ tồn tại trong log.
Có thể xác định bản ghi bị loại ở bước nào và vì nguyên nhân gì.
Lỗi cấp record không làm dừng toàn bộ batch.
Lỗi cấu trúc nghiêm trọng ngăn batch đi tiếp trước khi dữ liệu sai được lưu.
Có thể xử lý lại nhóm dữ liệu lỗi mà không cần chạy lại toàn bộ nguồn.
Số lượng đầu vào được đối chiếu với tổng số bản ghi thành công, bị reject và bị duplicate.
 
 
Sub-problem 4 — Làm thế nào để xác định pipeline đang xử lý đến đâu và lỗi xảy ra ở bước nào?
 
Hiện trạng:
Hệ thống đã có logging và theo dõi lần chạy, nhưng thông tin giữa các bước lấy dữ liệu, chuẩn hóa, kiểm tra và lưu trữ chưa được tổng hợp thành một trạng thái thống nhất.
 
Phương pháp thực hiện:
 
Chuẩn hóa vòng đời của mỗi lần chạy theo các giai đoạn chính: lấy dữ liệu, xử lý, kiểm tra, lưu trữ và hoàn thành.
Ghi nhận metrics tổng hợp tại từng giai đoạn, bao gồm số bản ghi nhận được, hợp lệ, bị loại, bị trùng và đã lưu.
Theo dõi thời gian xử lý, tiến độ trước và sau lần chạy, cùng nguyên nhân thất bại.
Kiểm thử các tình huống retry, duplicate, partial failure, invalid record và thay đổi cấu trúc dữ liệu.
 
Tiêu chí đánh giá:
 
Có thể xác định chính xác pipeline đang ở bước nào và lỗi xảy ra tại đâu.
Số lượng dữ liệu giữa các bước được ghi nhận và đối chiếu rõ ràng.
Partial failure được phản ánh đúng trạng thái và không bị ghi nhận thành completed.
Các tình huống lỗi chính được bao phủ bằng integration hoặc end-to-end test.
Pipeline tiếp tục xử lý ổn định với tập dữ liệu 100.000 bản ghi trong ngưỡng hiệu năng được thống nhất.
Các thay đổi không ảnh hưởng đến kết quả của luồng xử lý hiện tại.