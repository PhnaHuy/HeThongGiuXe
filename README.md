# Hệ thống quản lý bãi giữ xe

Ứng dụng desktop Python 3.13 / PySide6 / SQLite. G1–G2 quản lý khách, xe, lượt vào/ra có ảnh và nhật ký.

G3 bổ sung camera/MP4 và cấu hình nguồn.

G4 dùng checkpoint biển số `best.pt` cùng ByteTrack để phát hiện/theo dõi biển số;
camera cổng cố định hướng VÀO hoặc RA và đề xuất cho nhân viên.

G5 chỉ gửi crop biển số do `best.pt` cắt sang PaddleOCR trên môi trường riêng;
YOLOv8n nhận diện xe không còn được sử dụng. AI không tự tạo hay đóng lượt xe.
Checkpoint hiện được huấn luyện cho biển số xe máy; cần nghiệm thu riêng trên
camera thực tế. G6 bổ
sung màn hình tổng quan/thống kê, quản lý ngoại lệ, cấu hình sức chứa và tra
cứu audit theo quyền.

G7 bổ sung cấu hình polygon ô đỗ theo camera, trạng thái occupancy có ổn định theo nhiều khungvhình và đối chiếu riêng với số lượt đang gửi.

G8 bổ sung theme desktop thống nhất và báo cáo bàn giao; camera thật vẫn cần nghiệm thu riêng.

## Chạy trên Windows

Tại thư mục dự án, với môi trường hiện có:

```powershell
.\.venv\Scripts\python.exe run_app.py
```

Thiết lập môi trường mới: xem `scripts/setup_environment.ps1`. `.venv`,
`.venv-alpr` và `.venv-ocr-313` đều dùng
Python 3.13; hai môi trường nhận diện vẫn tách riêng để tránh xung đột OpenCV.

Giao diện chạy trên Qt main thread. Camera/model biển số chạy trong `VideoWorker`,
decoder bị cô lập trong tiến trình riêng để giới hạn lỗi/treo driver; OCR chạy
trong worker riêng và tiến trình runtime riêng. Truy vấn tổng quan/thống kê chạy
ở worker nghiệp vụ nền để không chặn thao tác giao diện.

Database mới khởi tạo ba tài khoản mẫu: `admin` / `admin123`,
`quanly` / `quanly123`, `nhanvien` / `nhanvien123`.
Đây là tài khoản demo; không đưa dữ liệu vận hành thật vào bản demo dùng mật khẩu mẫu.
Database có tài khoản sẵn sẽ không được seed lại.

## Dùng G3–G5

1. Quản trị viên mở tab **Nguồn hình — Camera / MP4** để cấu hình và lưu camera
   cổng một lần. Tab này cũng giữ các công cụ xem thử và MP4.
2. Trong tab **Vận hành bãi xe**, chọn camera đã lưu rồi nhấn **Xe vào** hoặc
   **Xe ra**. Hướng thao tác được chọn ngay tại đây, không phụ thuộc hướng đã
   lưu trong cấu hình camera. Hệ thống phát hiện biển và đưa ảnh/kết quả OCR
   vào đúng biểu mẫu; nhân viên kiểm tra rồi xác nhận. Nút **Dừng** kết thúc quét.
3. Khi chọn xe ra, OCR chỉ lọc các lượt đang gửi; nhân viên phải chọn đúng lượt,
   đối chiếu ảnh vào/ra và xác nhận thủ công. Khi chọn xe vào, nhân viên kiểm tra
   biển số/loại xe và xác nhận để tạo lượt.
4. OCR được làm nóng nền sau đăng nhập và giữ tiến trình PaddleOCR đã nạp model
   trong phiên làm việc để giảm độ trễ các lần đọc tiếp theo. Trong lần khởi động
   đầu hoặc khi nạp model, có thể cần chờ trạng thái **PaddleOCR đã sẵn sàng**;
   vẫn có thể nhập biển thủ công trong lúc chờ.
5. Để phát MP4 thử nghiệm hoặc cấu hình nguồn, quản trị viên mở tab
   **Nguồn hình — Camera / MP4**. Nhấn **Mở MP4 thử nghiệm…** để phát video cục bộ. Có tạm dừng/tiếp tục,
   tua bằng thanh trượt, dừng và phát lại sau khi hết video.
6. **Phát theo thời gian video** bật mặc định. Bỏ chọn để đọc đủ khung nhanh
   nhất mà giao diện nhận được. Cả hai chế độ MP4 đều không bỏ khung do UI chậm.
7. Quản trị viên nhấn **Tạo nguồn mới** (hoặc chọn **Chọn nguồn đã lưu** để
   nhập mới), điền tên, loại nguồn, địa chỉ (`0` cho webcam đầu tiên hoặc URL
   RTSP/HTTP) và mục đích. Mỗi camera cổng phải được cấu hình cố định là **Cổng
   vào** hoặc **Cổng ra**; **Khu đỗ** dành riêng cho theo dõi ô đỗ. Có thể nhấn
   **Phát / Kết nối / Xem thử** để kiểm tra trước khi lưu.
8. Nhấn **Lưu cấu hình nguồn**. Không cần vẽ vạch hoặc xác định chiều xe di
   chuyển; mỗi camera chỉ đề xuất sự kiện theo mục đích VÀO/RA đã lưu.
9. Khi camera mất hình, màn hình
   bỏ hình cũ, báo lỗi theo tên nguồn và tự thử lại. Dừng để kết thúc thử lại.
10. Chỉ model biển số `AI training\runs\detect\train\weights\best.pt` được dùng
   để phát hiện và theo dõi biển số. Mỗi track biển số mới trên camera cổng phát
   một đề xuất. Loại xe mặc định là xe máy vì checkpoint hiện được huấn luyện
   với lớp biển số xe máy.
11. Nếu một ảnh có nhiều vùng biển, detector chọn crop có chất lượng tốt nhất
   dựa trên độ tin cậy, độ nét và kích thước crop; chỉ crop đó được gửi sang
   PaddleOCR. Không tìm thấy biển thì PaddleOCR không được gọi.
12. OCR xử lý
   tối đa 5 ảnh nguồn; `best.pt` phải phát hiện và cắt được vùng biển số trước
   khi ảnh crop được gửi sang PaddleOCR. Không tìm thấy biển thì PaddleOCR không
   được gọi; nhân viên có thể nhập tay.
   Xe vào chỉ được tạo sau khi nhân viên xác nhận; xe ra OCR chỉ lọc danh sách,
   nhân viên phải chọn đúng lượt, đối chiếu ảnh và xác nhận thủ công.
13. Ảnh tự chọn ở bước vào/ra cũng có thể chạy OCR. OCR thô, biển đề xuất, độ
   tin cậy và ảnh cắt biển được ghi vào audit/bằng chứng khi nhân viên xác nhận.
   Nếu không đọc được hoặc không tìm thấy vùng biển, tiếp tục quy trình thủ công.

MP4 trong tab xem thử vẫn hỗ trợ chuyển đề xuất sang quy trình xác nhận thủ công.
MP4 không tự tạo hoặc đóng lượt.

## Thiết lập webcam và URL camera

1. Kết nối webcam với máy tính, hoặc kết nối camera IP và máy tính vào mạng có thể
   liên lạc với nhau. Bật dịch vụ phát hình của camera và lấy **địa chỉ luồng video**
   từ hướng dẫn hoặc trang cấu hình camera; địa chỉ trang quản trị thường không phải
   địa chỉ luồng.
2. Đăng nhập quản trị viên, mở **Nguồn hình — Camera / MP4**, chọn **Tạo nguồn mới**,
   nhập tên, chọn **Camera trực tiếp** và mục đích VÀO hoặc RA. Trong trường nguồn, nhập `0`, `1`,
   `2`, ... cho webcam tương ứng, hoặc URL đầy đủ của luồng RTSP/RTSPS/HTTP/HTTPS.
   Ví dụ minh họa (đường dẫn và cổng thực tế tùy camera):
   `rtsp://user:password@192.168.1.150:8554/live` hoặc
   `http://192.168.1.100:8080/video` (luồng MJPEG). Nếu tài khoản hoặc mật khẩu có
   ký tự đặc biệt như `@`, `:` hoặc `/`, mã hóa phần đó theo URL, ví dụ `@` thành `%40`.
   Trường nguồn mới để trống: nhập URL thực tế của camera hoặc chỉ số webcam.
   Mỗi camera cần một nguồn riêng với URL, tài khoản, cổng và đường dẫn theo cấu hình
   của thiết bị hoặc đầu ghi. Lặp lại các bước tạo và lưu cho từng camera; chọn nguồn
   muốn xem trong danh sách. Ứng dụng hiện phát một nguồn tại một thời điểm.
3. Nhấn **Phát / Kết nối / Xem thử**, chờ hình xuất hiện, sau đó nhấn **Lưu cấu hình
   nguồn**. Chỉ camera khu đỗ mới cần cấu hình polygon ô đỗ. Nguồn đã lưu xuất hiện
   trong danh sách cho nhân viên lựa chọn.
4. Nếu không có hình, kiểm tra nguồn điện, địa chỉ IP, cổng, tài khoản, đường dẫn luồng,
   kết nối mạng và tường lửa; thử chính URL luồng trong một trình phát hỗ trợ RTSP/HTTP
   trên cùng máy. Với webcam, kiểm tra quyền camera của Windows, đóng ứng dụng khác
   đang dùng camera và thử chỉ số khác. Ứng dụng tự thử kết nối lại khi mất hình; nhấn
   **Dừng** để dừng thử lại. Một số thiết bị yêu cầu bật RTSP hoặc tạo tài khoản riêng.

URL có mật khẩu được che trong giao diện và không ghi vào audit, nhưng được lưu trong
database cục bộ dưới dạng văn bản; bảo vệ database và không chia sẻ URL có thông tin đăng nhập.
Khả năng giải mã và giao thức phụ thuộc vào bản OpenCV/FFmpeg và định dạng của camera.

## Dùng G6 — quản lý và giám sát

- **Quản lý/Quản trị viên:** tab **Tổng quan và thống kê** hiển thị số lượt đang
  gửi, chỗ còn theo loại và thời điểm làm mới; thống kê vào/ra có thể lọc từ ngày
  đến ngày. Tồn tại và lượt vào/ra được đếm từ dữ liệu lượt, không từ số ô đỗ.
- **Quản lý/Quản trị viên:** tab **Theo dõi bất thường** lọc chưa/đã xử lý, xem
  lý do/kết quả, nhân viên và ảnh bằng chứng; sự cố xe ra không khớp có thể được
  đánh dấu đã xử lý kèm ghi chú. Các lượt cần xử lý được giải quyết bằng audit,
  không xóa dấu vết ban đầu.
- **Quản trị viên:** tab **Cấu hình sức chứa** lưu giới hạn xe máy/ô tô. Tổng sức
  chứa toàn bãi được tính bằng tổng hai giới hạn; cấu hình theo khu chưa có vì
  dữ liệu khu/ô đỗ thuộc G7. Thay đổi được ghi audit và phản ánh ngay lên màn hình
  vận hành.
- **Quản trị viên:** tìm hồ sơ theo tên hoặc biển số, sửa biển/loại xe có kiểm tra
  trùng và audit trước/sau. Nhân viên vẫn có thể đăng ký khách/xe theo luồng vận
  hành nhưng không được sửa hồ sơ.
- **Quản lý/Quản trị viên:** tab nhật ký cho phép lọc theo tài khoản, loại hành
  động và ngày; nhật ký chỉ xem, không sửa/xóa.

## Dùng G7 — giám sát ô đỗ

1. Quản trị viên tạo/chọn nguồn, đặt mục đích **Khu đỗ**, phát/xem thử hình
   camera rồi nhập mã ô (ví dụ `A01`).
2. Nhấn **Bắt đầu vẽ polygon**, bấm các đỉnh ranh ô trên hình và chọn **Lưu
   polygon**. Chọn lại mã ô để vẽ thay thế; dùng **Xóa ô đang chọn** để xóa.
   Lưu cấu hình camera sau khi hoàn tất. Mỗi polygon phải có mã duy nhất trong
   camera đó và không tự giao nhau.
3. Các vùng được vẽ màu theo trạng thái. Ứng dụng yêu cầu ba khung liên tiếp
   cùng kết quả trước khi báo **Trống** hoặc **Có xe**; trạng thái chưa ổn định,
   dừng/tua/mất hình/quá hạn sẽ là **Không xác định**.
4. Phần tổng hợp hiển thị số ô theo trạng thái, đồng thời hiển thị riêng số
   lượt đang gửi toàn bãi và chênh lệch tham khảo khi toàn bộ ô đã xác định.
   Phép so sánh không đồng nhất nếu camera chỉ quan sát một phần bãi; số ô camera
   không thay thế số lượt vận hành.

Trạng thái ô dựa trên giao giữa polygon và bounding box biển số; phải hiệu chỉnh
polygon và nghiệm thu với camera thật trước khi dùng làm số liệu chính thức.
Detector hiện chưa có cơ chế phát hiện độc lập camera bị dịch hoặc vùng bị che
khuất, nên xe bị bỏ sót liên tiếp có thể khiến ô bị báo trống.

## Dữ liệu và cấu hình

- Database: `data/parking.db`; ảnh bằng chứng: `data/evidence/`.
- Nguồn hình: bảng `video_sources`, được thêm khi khởi động; không dựng lại bảng lượt xe.
- Polygon ô đỗ G7 lưu trong `video_sources.parking_spaces`; khởi động ứng dụng
  tự cộng cột này cho database cũ mà không xóa nguồn hình đã lưu.
- Sức chứa G6: bảng `parking_capacity`, được thêm tự động khi khởi động. Cấu hình
  mặc định trên database chưa có dòng là 50 xe máy và 20 ô tô; giá trị đã lưu
  được giữ qua lần khởi động sau.
- URL có thể chứa thông tin đăng nhập camera; ô nhập được che, audit không ghi URL.
  URL vẫn nằm trong database cục bộ, vì vậy chỉ chia sẻ dữ liệu demo đã loại bỏ thông tin này.
- Các biến môi trường G3 (đơn vị giây): `PARKING_VIDEO_OPEN_TIMEOUT_S` (8),
  `PARKING_VIDEO_READ_TIMEOUT_S` (4), `PARKING_VIDEO_RECONNECT_DELAY_S` (2),
  `PARKING_VIDEO_STALE_AFTER_S` (3). Giá trị phải dương và hữu hạn; khởi động lại
  ứng dụng sau khi thay đổi.
- Cấu hình model biển số: `PARKING_PLATE_MODEL` (mặc định
  `AI training\runs\detect\train\weights\best.pt`), `PARKING_PLATE_CONFIDENCE`
  (0.25), `PARKING_PLATE_IMAGE_SIZE` (640) và `PARKING_PLATE_DEVICE` (`cpu`).
  Mỗi camera cổng dùng mục đích VÀO hoặc RA
  đã lưu để gán hướng đề xuất.
  Model không được tự tải từ mạng; thiếu model hoặc lỗi suy luận sẽ hiện trạng thái lỗi.
- OCR mặc định dùng PaddleOCR trong `.venv-ocr-313`.
  Cấu hình runtime bằng `PARKING_OCR_PYTHON`,
  `PARKING_OCR_WORKER`, `PARKING_OCR_CACHE`, `PARKING_OCR_TIMEOUT_S` (30 giây)
  và `PARKING_OCR_MAX_SAMPLES` (5). `PaddleOCR`/`PaddlePaddle` không được nạp vào
  tiến trình giao diện; worker tắt oneDNN để tránh lỗi runtime CPU đã kiểm chứng
  trên Windows. Worker không tự tải model khi cache OCR chưa có sẵn. Nếu cần chuẩn bị
  model lần đầu, sau khi xem xét cho phép tải model chính thức, chạy:

  ```powershell
  .\.venv-ocr-313\Scripts\python.exe scripts\check_vision.py --component ocr --allow-model-download
  ```

## Kiểm tra OCR G5

```powershell
.\.venv\Scripts\python.exe scripts\check_ocr.py
```

Lệnh trên dùng ảnh biển tổng hợp; có thể truyền `--image <đường_dẫn_ảnh>` để
kiểm tra ảnh cục bộ. Kết quả ảnh tổng hợp chỉ xác nhận tích hợp runtime, không
đại diện độ chính xác trên biển số/camera thực tế.
