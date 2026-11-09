# Hệ thống quản lý bãi giữ xe

Ứng dụng desktop Python 3.13 / PySide6 / SQLite. G1–G2 quản lý khách, xe,
lượt vào/ra có ảnh và nhật ký. G3 bổ sung camera/MP4 và cấu hình nguồn/vạch.
G4 tích hợp YOLOv8n/ByteTrack, phát hiện hướng qua vạch và đề xuất cho nhân viên;
G5 bổ sung đề xuất vùng biển và OCR PaddleOCR trên môi trường riêng; AI không tự
tạo hay đóng lượt xe. Detector vùng biển hiện là heuristic OpenCV, chưa thay thế
được model biển số chuyên dụng đã đánh giá. G6 bổ sung màn hình tổng quan/thống kê,
quản lý ngoại lệ, cấu hình sức chứa và tra cứu audit theo quyền. G7 bổ sung cấu
hình polygon ô đỗ theo camera, trạng thái occupancy có ổn định theo nhiều khung
hình và đối chiếu riêng với số lượt đang gửi. G8 bổ sung theme desktop thống
nhất và báo cáo bàn giao; camera thật vẫn cần nghiệm thu riêng.

## Chạy trên Windows

Tại thư mục dự án, với môi trường hiện có:

```powershell
.\.venv\Scripts\python.exe run_app.py
```

Thiết lập môi trường mới: xem `scripts/setup_environment.ps1` và
`docs/G0_COMPATIBILITY.md`. `.venv`, `.venv-alpr` và `.venv-ocr-313` đều dùng
Python 3.13; hai môi trường nhận diện vẫn tách riêng để tránh xung đột OpenCV.

Giao diện chạy trên Qt main thread. Camera/YOLO chạy trong `VideoWorker`,
decoder bị cô lập trong tiến trình riêng để giới hạn lỗi/treo driver; OCR chạy
trong worker riêng và tiến trình runtime riêng. Truy vấn tổng quan/thống kê chạy
ở worker nghiệp vụ nền để không chặn thao tác giao diện.

Database mới khởi tạo ba tài khoản mẫu: `admin` / `admin123`,
`quanly` / `quanly123`, `nhanvien` / `nhanvien123`.
Đây là tài khoản demo; không đưa dữ liệu vận hành thật vào bản demo dùng mật khẩu mẫu.
Database có tài khoản sẵn sẽ không được seed lại.

## Dùng G3–G5

1. Đăng nhập, mở tab **Nguồn hình — Camera / MP4**.
2. Nhấn **Mở MP4 thử nghiệm…** để phát video cục bộ. Có tạm dừng/tiếp tục,
   tua bằng thanh trượt, dừng và phát lại sau khi hết video.
3. **Phát theo thời gian video** bật mặc định. Bỏ chọn để đọc đủ khung nhanh
   nhất mà giao diện nhận được. Cả hai chế độ MP4 đều không bỏ khung do UI chậm.
4. Quản trị viên nhấn **Tạo nguồn mới** (hoặc chọn **Chọn nguồn đã lưu** để
   nhập mới), điền tên, loại nguồn, địa chỉ (`0` cho webcam đầu tiên hoặc URL
   RTSP/HTTP) và mục đích cổng/khu đỗ. Có thể nhấn **Phát / Kết nối / Xem thử**
   để kiểm tra trước khi lưu.
5. Nút **Lưu cấu hình và vạch** luôn nằm dưới cùng panel cấu hình; trường hợp
   cửa sổ thấp, cuộn phần nội dung panel. Trên hình, kéo từ A tới B để đặt vạch;
   mũi tên VÀO là chiều qua vạch vào bãi. Đảo chiều bằng ô chọn, rồi lưu để áp
   dụng. Vạch gắn riêng từng nguồn.
6. Nhân viên chọn camera đã lưu trong danh sách. Khi camera mất hình, màn hình
   bỏ hình cũ, báo lỗi theo tên nguồn và tự thử lại. Dừng để kết thúc thử lại.
7. Model YOLOv8n cục bộ mặc định nằm ở `models/yolov8n.pt`. Khi có xe được
   phát hiện, màn hình vẽ khung, loại xe, độ tin cậy và ID track. Cấu hình vạch
   mới làm phát sinh đề xuất VÀO/RA sau khi xe đi qua ổn định.
8. Với camera trực tiếp, chọn sự kiện và chuyển sang bước xác nhận. OCR xử lý
   nền tối đa 5 ảnh xe gần nhất, điền biển số đề xuất và cho phép sửa/nhập tay.
   Xe vào chỉ được tạo sau khi nhân viên xác nhận; xe ra OCR chỉ lọc danh sách,
   nhân viên phải chọn đúng lượt, đối chiếu ảnh và xác nhận thủ công.
9. Ảnh tự chọn ở bước vào/ra cũng có thể chạy OCR. OCR thô, biển đề xuất, độ
   tin cậy và ảnh cắt biển được ghi vào audit/bằng chứng khi nhân viên xác nhận.
   Nếu không đọc được hoặc không tìm thấy vùng biển, tiếp tục quy trình thủ công.

MP4 hỗ trợ xác nhận xe vào/ra như camera trực tiếp, kể cả khi đang tạm dừng.
Chọn sự kiện xe qua vạch rồi nhấn **Chuyển đề xuất sang bước xác nhận**;
kiểm tra ảnh/biển số và xác nhận xe vào, hoặc chọn lượt đang gửi để xác nhận xe ra.
Lượt được lưu vào dữ liệu vận hành hiện tại và cập nhật sức chứa như bình thường;
tracking không tự động tạo hoặc đóng lượt.

## Thiết lập webcam và URL camera

1. Kết nối webcam với máy tính, hoặc kết nối camera IP và máy tính vào mạng có thể
   liên lạc với nhau. Bật dịch vụ phát hình của camera và lấy **địa chỉ luồng video**
   từ hướng dẫn hoặc trang cấu hình camera; địa chỉ trang quản trị thường không phải
   địa chỉ luồng.
2. Đăng nhập quản trị viên, mở **Nguồn hình — Camera / MP4**, chọn **Tạo nguồn mới**,
   nhập tên, chọn **Camera trực tiếp** và mục đích. Trong trường nguồn, nhập `0`, `1`,
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
   và vạch**. Có thể vẽ vạch hoặc cấu hình ô đỗ trước khi lưu. Nguồn đã lưu xuất hiện
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

Trạng thái ô dựa trên giao giữa polygon và bounding box YOLO; phải hiệu chỉnh
polygon và nghiệm thu với camera thật trước khi dùng làm số liệu chính thức.
Detector hiện chưa có cơ chế phát hiện độc lập camera bị dịch hoặc vùng bị che
khuất, nên xe bị bỏ sót liên tiếp có thể khiến ô bị báo trống. Xem
[`docs/G7_ACCEPTANCE.md`](docs/G7_ACCEPTANCE.md) để biết phạm vi và quy trình
kiểm chứng.

## Dữ liệu và cấu hình

- Database: `data/parking.db`; ảnh bằng chứng: `data/evidence/`.
- Nguồn/vạch: bảng `video_sources`, được thêm khi khởi động; không dựng lại bảng lượt xe.
- Polygon ô đỗ G7 lưu trong `video_sources.parking_spaces`; khởi động ứng dụng
  tự cộng cột này cho database cũ mà không xóa nguồn/vạch đã lưu.
- Sức chứa G6: bảng `parking_capacity`, được thêm tự động khi khởi động. Cấu hình
  mặc định trên database chưa có dòng là 50 xe máy và 20 ô tô; giá trị đã lưu
  được giữ qua lần khởi động sau.
- URL có thể chứa thông tin đăng nhập camera; ô nhập được che, audit không ghi URL.
  URL vẫn nằm trong database cục bộ, vì vậy chỉ chia sẻ dữ liệu demo đã loại bỏ thông tin này.
- Các biến môi trường G3 (đơn vị giây): `PARKING_VIDEO_OPEN_TIMEOUT_S` (8),
  `PARKING_VIDEO_READ_TIMEOUT_S` (4), `PARKING_VIDEO_RECONNECT_DELAY_S` (2),
  `PARKING_VIDEO_STALE_AFTER_S` (3). Giá trị phải dương và hữu hạn; khởi động lại
  ứng dụng sau khi thay đổi.
- Cấu hình G4: `PARKING_VISION_MODEL` (đường dẫn model local, mặc định
  `models/yolov8n.pt`), `PARKING_VISION_CONFIDENCE` (0.25),
  `PARKING_VISION_IMAGE_SIZE` (640), `PARKING_VISION_DEVICE` (`cpu`),
  `PARKING_CROSSING_DEADBAND` (0.015), `PARKING_CROSSING_STABLE_FRAMES` (2),
  `PARKING_TRACK_STALE_FRAMES` (300). Cần cấu hình vạch trên camera để sinh đề xuất.
  Model không được tự tải từ mạng; thiếu model hoặc lỗi suy luận sẽ hiện trạng thái lỗi.
- OCR mặc định dùng **YOLO11s biển số + Fast Plate OCR** trong `.venv-alpr`.
  Xem [cài đặt, cấu hình và kết quả trên video thực tế](docs/PLATE_RECOGNITION.md).
  Chọn `PARKING_OCR_BACKEND=paddle` để dùng PaddleOCR dự phòng trong `.venv-ocr-313`.
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

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Kiểm thử dùng database trong RAM và ảnh/video tổng hợp ở thư mục tạm;
không truy cập webcam hoặc database vận hành. Nếu môi trường hạn chế quyền
thư mục Temp, dùng `--basetemp` trỏ tới **một thư mục mới dành riêng cho test**;
pytest có thể xóa nội dung thư mục được chỉ định.

Phạm vi và bằng chứng nghiệm thu G8: [docs/G8_ACCEPTANCE.md](docs/G8_ACCEPTANCE.md).
Các giai đoạn trước: [G3](docs/G3_ACCEPTANCE.md),
[G4](docs/G4_ACCEPTANCE.md), [G5](docs/G5_ACCEPTANCE.md),
[G6](docs/G6_ACCEPTANCE.md), [G7](docs/G7_ACCEPTANCE.md).
