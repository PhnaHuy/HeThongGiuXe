# G7 — Giám sát từng ô đỗ

## Phạm vi thực hiện

- Mỗi nguồn hình có mục đích **Khu đỗ** có thể lưu nhiều ô với mã riêng và
  polygon chuẩn hóa theo kích thước hình. Polygon được quản trị viên vẽ bằng các
  điểm nhấp chuột trên preview, chọn lại, vẽ đè hoặc xóa.
- Cấu hình kiểm tra mã trùng (không phân biệt hoa/thường), tọa độ hữu hạn trong
  `[0, 1]`, số đỉnh, diện tích và cạnh tự giao nhau. Polygon lưu trong bảng
  `video_sources`; migration cộng cột nullable cho database G3–G6 hiện có.
- `ParkingSpaceMonitor` dùng detection xe có sẵn từ YOLO, không chạy detector
  thứ hai. Một ô chỉ đổi sang **Trống** hoặc **Có xe** sau ba khung liên tiếp
  cùng kết quả; trong thời gian chờ, kết quả là **Không xác định**.
- Dừng, tua, mất kết nối, lỗi nguồn, hết MP4 và hình quá hạn xóa preview cũ và
  đưa mọi ô về **Không xác định**. Overlay hiển thị trạng thái trên từng polygon;
  phần tổng hợp luôn nêu số trống/có xe/không xác định.
- Nếu ứng dụng được nối với `ParkingService`, tổng số lượt đang gửi toàn bãi và
  chênh lệch tham khảo với số ô camera quan sát được hiển thị tách biệt. Khi còn
  ô không xác định, giao diện không báo chênh lệch như một phép so sánh đầy đủ.
  Chênh lệch không cùng phạm vi nếu camera chỉ quan sát một phần bãi.

## Kiểm tra tự động

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit\test_parking_space_monitor.py tests\unit\test_video_contracts.py tests\integration\test_source_service.py tests\acceptance\test_g7_scenarios.py
```

Các bài kiểm tra bao phủ validation hình học, ổn định/đặt lại trạng thái, ô
ngoài vùng detection, serialize/audit polygon, nâng cấp bảng `video_sources`
kiểu cũ, thao tác polygon trên Qt canvas và hiển thị tổng hợp/đối chiếu độc lập.

## Kiểm chứng vận hành còn cần thực hiện

Kiểm thử tổng hợp không chứng minh độ chính xác trên camera thật. Trước khi dùng
số ô để ra quyết định vận hành:

1. Quản trị viên chọn camera có mục đích **Khu đỗ**, phát/xem thử và vẽ polygon
   sát ranh từng ô; lưu cấu hình rồi khởi động lại ứng dụng để xác nhận dữ liệu
   được giữ.
2. So sánh từng trạng thái với quan sát thủ công trên các cảnh trống, có xe,
   xe nằm sát ranh, nhiều xe, thay đổi ánh sáng, che khuất và mất/kết nối lại.
3. Ghi rõ camera, góc, độ phân giải, thời gian lấy mẫu, tỷ lệ đúng/sai và số ô
   không xác định. Hiệu chỉnh số khung ổn định/ngưỡng overlap chỉ khi có dữ liệu
   đánh giá hợp lệ.

Giới hạn hiện tại: occupancy là heuristic từ bounding box YOLO giao với polygon.
Không có kiểm tra độc lập về độ che khuất hoặc camera bị dịch; nếu vật cản làm
YOLO bỏ sót xe liên tiếp, ô có thể bị đánh dấu trống. Vì vậy kết quả hiện tại là
tham khảo, không phải kiểm kê chính thức và không thay thế lượt xe đã xác nhận.
