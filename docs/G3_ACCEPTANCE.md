# G3 — Nguồn hình và cấu hình

Ngày triển khai: 27/10/2026. Module M02, M09; chính sách mô phỏng liên quan M06.

## Phạm vi

| Story | Phần triển khai G3 | Giới hạn nghiệm thu |
|---|---|---|
| NV-02 | Chọn nguồn đã lưu hoặc MP4 cục bộ; xem hình; play/pause/tua; trạng thái và chế độ thử nghiệm | Hiển thị kết quả nhận dạng còn phụ thuộc G4–G5 |
| QT-02 | Admin thêm/sửa/xóa nguồn, tên, loại, mục đích; xem thử trước lưu; trạng thái theo tên camera | Camera vật lý/RTSP cần nghiệm thu tại bãi |
| QT-03 | Vẽ/sửa/xóa/lưu vạch và chiều vào trên từng nguồn; tọa độ chuẩn hóa theo hình, bỏ vùng viền | Polygon ô đỗ ở G7; phát hiện qua vạch ở G4 |
| CM-03 | Lỗi nguồn, timeout, mất hình, thử kết nối lại; xóa hình quá hạn; reset phiên luồng | Test lỗi camera sử dụng adapter giả lập; chưa kiểm chứng thiết bị thật |

## Thiết kế và vòng đời

- `domain/video.py`: `SourceConfig`, `GateLine`, `Frame`, loại nguồn/trạng thái,
  cấu hình thời gian chờ. Domain không import Qt/OpenCV.
- `SourceService`: kiểm tra lại tài khoản trong DB khi xem/lưu; chỉ admin lưu
  cấu hình. Nguồn và audit ghi cùng transaction. Không ghi endpoint vào audit.
- `OpenCVVideoSource`: camera và MP4 dùng cùng port `VideoSource`; MP4 dùng
  frame index/media time, thời điểm quan sát UTC nằm riêng trong `Frame`.
- `IsolatedVideoSource`: đọc/giải mã OpenCV trong tiến trình con cục bộ không có
  service nghiệp vụ. Supervisor có deadline và hủy được khi driver native treo;
  đóng mềm trước, sau đó kết thúc tiến trình nếu không phản hồi. Không terminate QThread.
- `VideoWorker`: QThread điều phối, signal/slot cập nhật GUI. Live chỉ giữ một
  frame mới nhất và đếm khung hiển thị bị thay; MP4 đợi consumer nhận từng frame.
  Không tuyên bố đã quan sát đủ sự kiện nếu live bỏ khung.
- Mỗi lần mở/kết nối lại/tua có `stream_id` mới và signal `stream_reset` để
  G4/G5 xóa tracker, bộ đếm qua vạch và tổng hợp OCR. Chưa có tracker/OCR ở G3.
- Đổi nguồn, đóng cửa sổ, đăng xuất: yêu cầu dừng, đợi signal `finished` rồi
  mở nguồn tiếp/đóng cửa sổ. UI không chờ vòng đọc blocking.
- Chuyển BGR sang QImage bằng bản sao sở hữu bộ nhớ riêng; tọa độ vạch tính trên
  vùng ảnh sau giữ tỷ lệ, không tính viền đen. Với vạch A→B, mũi tên vào tương
  ứng phía dương của tích có hướng khi `entry_positive=True`.
- MP4 hỗ trợ chuyển đề xuất để xác nhận vào/ra như camera. Tab vận hành vẫn mở;
  ParkingService chấp nhận nguồn MP4. Lượt được lưu trong database vận hành
  sau khi người dùng xác nhận, không tự tạo/đóng lượt từ tracking.

## Kiểm chứng

Các test G3 nằm trong:

- `tests/unit/test_video_contracts.py`: cấu hình sai, vạch suy biến/ngoài hình,
  timeout không hợp lệ, không lộ endpoint trong repr.
- `tests/integration/test_source_service.py`: quyền admin, khóa tài khoản khi
  phiên cũ còn mở, vạch riêng từng nguồn, audit/rollback, xác nhận giao dịch MP4.
- `tests/integration/test_video_source.py`: OpenCV giải mã MP4 tổng hợp thật qua
  tiến trình con, đủ frame, EOF, tua, file hỏng, hủy và timeout tiến trình không phản hồi.
- `tests/acceptance/test_g3_scenarios.py`: Qt offscreen phát/tạm dừng/tua/reset,
  mất/kết nối lại camera giả lập, buffer live giới hạn, vẽ và lưu vạch qua UI,
  chuyển nguồn, vận hành với MP4, đóng cửa sổ, hình quá hạn và khóa tài khoản.

Kết quả chạy cuối được ghi ở phần cập nhật tiến độ trong `KE_HOACH_TRIEN_KHAI.md`.
Video được sinh bằng OpenCV từ mảng màu, không dùng hình/biển số khách hàng thật.
Không chạy model AI, không mở webcam hoặc kết nối camera mạng trong bộ test này.

## Việc cần kiểm chứng tại máy/bãi thật

1. Webcam thực tế, URL RTSP/HTTP, quyền truy cập thiết bị, rút/cắm lại camera.
2. Đo độ trễ/FPS/CPU/bộ nhớ theo độ phân giải và driver; G3 chưa có cam kết hiệu năng.
3. OpenCV báo frame count/media time phụ thuộc codec. File lỗi trước frame count
   báo lỗi; nếu codec không cung cấp count thì kết thúc sau khung cuối được coi là EOF.
4. Driver không nhả thiết bị khi treo sẽ bị kết thúc cùng tiến trình đọc sau thời gian chờ;
   cần kiểm tra khả năng mở lại chính driver đó trên máy mục tiêu.

Tham khảo thiết kế: [Qt QThread](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html),
[OpenCV Video I/O properties](https://docs.opencv.org/4.12.0/d4/d15/group__videoio__flags__base.html).
