# G8 — Kiểm thử cuối, giao diện và bàn giao

## Trạng thái

Phần mềm G1–G7 và giao diện bàn giao G8 đã được kiểm thử tự động trong môi
trường Windows/Python 3.11 (kết quả lịch sử). Đợt nâng cấp ngày 04/11/2026 đã
chạy lại toàn bộ suite trên Python 3.13.17: **165 test đạt**; smoke test YOLO/
ByteTrack và OCR tổng hợp cũng đạt. Nghiệm thu camera thật và chỉ tiêu AI trên dữ liệu
thực **chưa đạt/không thể kết luận** vì phiên làm việc này không có camera bãi xe
hay tập video gán nhãn. Không dùng smoke test tổng hợp để tuyên bố độ chính xác
hoặc sẵn sàng vận hành thương mại.

## Phạm vi hoàn tất

- Thống nhất giao diện desktop bằng theme sáng: nền trung tính, màu teal làm
  điểm nhấn, phân cấp tiêu đề, tab, nút, ô nhập, bảng và status bar. Theme được
  cài ở vòng đời ứng dụng trước khi mở màn hình đăng nhập.
- Cửa sổ chính có tiêu đề, thông tin người dùng rõ ràng, vùng nội dung rộng hơn
  và status bar nhấn mạnh AI chỉ đề xuất, nhân viên xác nhận.
- Trang nguồn hình dùng splitter có thể kéo giữa preview và editor; form cấu hình
  chuyển label lên trên trường nhập, panel có thanh cuộn để giữ các nút không
  chồng lấn ở cửa sổ thấp/hẹp.
- Chạy lại luồng khởi động/đăng nhập, các acceptance test G1–G7, test giao diện
  G8 và toàn bộ test regression. Các kiểm thử giao dịch, quyền, audit, camera/
  MP4, OCR, polygon và trạng thái mất hình nằm ở suite tương ứng.
- Kết quả tại mốc bàn giao Python 3.11: **130 test đạt**; `ruff check .` đạt; `ruff format --check .`
  đạt (91 tệp Python đã đúng định dạng).
- Smoke test lịch sử: Python 3.11.15; YOLOv8n CPU và ByteTrack chạy
  được trên fixture tổng hợp; PaddleOCR đọc fixture ký tự tổng hợp
  `51A12345` với confidence `0.99965`.
- Đã kiểm tra máy thử: Intel Core i5-12500H, RAM 15.7 GiB, NVIDIA RTX 3050
  Laptop 4 GiB và Intel Iris Xe. PyTorch là `2.14.1+cpu`,
  `torch.cuda.is_available()` trả `False`; cấu hình vận hành mặc định là CPU.
  Chưa có benchmark end-to-end được ghi nhận trên camera bãi thật.
- Full Ruff lint và formatting đạt tại mốc bàn giao Python 3.11 sau khi chuẩn
  hóa định dạng test khởi động ứng dụng.
- Xác nhận Python 3.13: inference YOLOv8n CPU trên ảnh tổng hợp, ByteTrack,
  OpenCV MP4 và PaddleOCR CPU đều chạy; đây không phải benchmark FPS hoặc đánh
  giá độ chính xác trên dữ liệu bãi xe.

## Lệnh kiểm chứng

Từ thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe scripts\check_vision.py --component vision
.\.venv\Scripts\python.exe scripts\check_ocr.py
```

Kết quả chạy trong phiên bàn giao: 130 test, Ruff check, Ruff format,
YOLO/ByteTrack smoke và OCR fixture đều đạt. YOLO smoke ghi elapsed 2.333 giây
cho bước `yolo_cpu`, bao gồm khởi tạo model và các bước kiểm tra tổng hợp,
**không phải FPS xử lý video**. OCR fixture chỉ chứng minh tích hợp; không đại
diện OCR biển số thực.

## Quy trình nghiệm thu còn bắt buộc trên máy mục tiêu

1. Cài theo `scripts/setup_environment.ps1`, mở ứng dụng bằng lệnh README và
   đăng nhập từng vai trò mẫu; đổi mật khẩu demo trước khi dùng dữ liệu vận hành.
2. Với từng vai trò, kiểm tra các tab/quyền và thực hiện chu trình khách/xe, xác
   nhận vào, tìm lượt, xác nhận ra, ngoại lệ và audit trên database thử nghiệm.
3. Với video MP4, xác minh dừng/tua/hết video và đảm bảo không thể tạo/đóng lượt
   thật trong chế độ mô phỏng.
4. Trên camera cổng/khu đỗ được cho phép sử dụng, kiểm tra mất/kết nối lại, ảnh
   quá hạn, cấu hình vạch/polygon đúng camera và trạng thái không xác định khi
   thiếu hình. Không thử bằng URL có credential trong tài liệu hoặc audit.
5. Đánh giá trên tập video/ảnh có quyền sử dụng, gán nhãn và tách theo camera/
   phiên quay để tránh leakage giữa các khung gần nhau. Báo cáo precision/
   recall/F1 và confusion matrix cho xe/hướng, exact-match và tỷ lệ tìm vùng cho
   biển số, cùng độ chính xác từng ô, khoảng tin cậy, false positives/negatives
   theo ánh sáng/góc/che khuất. Giữ test set độc lập; không tinh chỉnh trên test.
6. Đo throughput và độ trễ p50/p95 toàn pipeline trên phần cứng bàn giao, ghi
   model/hash, độ phân giải, số camera đồng thời, device, CPU/GPU, RAM/VRAM,
   số khung bỏ và nhiệt độ/tải trong khoảng chạy đủ dài.
7. Kiểm tra backup/restore database và thư mục ảnh trên bản sao dữ liệu; không
   chạy thử nghiệm phá hủy trên dữ liệu vận hành.

## Ma trận điều kiện chấp nhận

| Nhóm yêu cầu | Bao phủ tự động hiện có | Kết quả / việc còn lại |
|---|---|---|
| NV-01, QT-01, M01 | Unit/integration và acceptance đăng nhập, tài khoản khóa, vai trò | Tự động đạt; kiểm tra quy trình đổi mật khẩu demo khi triển khai. |
| NV-03–04, KH-01, QT-05, M05 | CRUD hồ sơ, chuẩn hóa/trùng biển, sửa có audit | Tự động đạt; UAT vai trò trên máy mục tiêu. |
| NV-05–10, KH-02–03, M06/M08/M10 | Xác nhận vào/ra, lượt vãng lai, ảnh, ngoại lệ, snapshot, audit, MP4 guard | Tự động đạt; cần UAT thao tác thật và dữ liệu thử độc lập. |
| NV-02, QT-02–03, CM-01/03, M02 | Source service, worker, MP4/camera giả lập, timeout/reset và UI | Tự động đạt với fixture; cần camera thật, mạng và vị trí đặt camera. |
| NV-11, QL-03, QT-06, M09 | Tra cứu/lịch sử/thống kê/audit theo quyền và bộ lọc | Tự động đạt; thống kê hiệu năng với dữ liệu quy mô triển khai chưa đo. |
| NV-12, QL-01, QT-04, M07 | Capacity summary, cảnh báo, cấu hình và dashboard | Tự động đạt; cấu hình theo khu không có trong mô hình nghiệp vụ hiện tại. |
| QL-02, CM-02, G7 | Polygon, occupancy ổn định, unknown/reset và so sánh riêng với lượt mở | Test tổng hợp đạt; độ chính xác từng ô cần camera và ground truth. |
| NV-08 và G5 OCR | OCR worker, dữ liệu fixture, không tự xác nhận | Fixture đạt; detector vùng biển heuristic và OCR thực chưa được định lượng. |
| G8 giao diện | Theme toàn ứng dụng, smoke test cài theme | Tự động đạt; xem trực tiếp trên màn hình Windows để đánh giá scaling/độ phân giải. |

## Hạn chế và quyết định bàn giao

- Không có test set bãi xe gán nhãn; vì vậy không báo cáo precision, recall,
  exact-match hay độ chính xác ô đỗ. Không thay các giá trị thiếu bằng kết quả
  trên ảnh/video tổng hợp.
- Smoke test YOLO ghi nhận CPU model hoạt động nhưng chưa có đo throughput toàn
  pipeline. Có GPU trên máy nhưng dependency hiện khóa PyTorch CPU; chưa đổi
  device hoặc cài CUDA ở mốc này.
- Ô đỗ dựa trên overlap bounding box; chưa tự phát hiện camera bị xê dịch hoặc
  vật thể che khuất khi detector bỏ sót xe liên tiếp.
- Ứng dụng có thể chạy demo/kiểm thử theo README. Chỉ đưa vào vận hành thật sau
  khi hoàn tất quy trình nghiệm thu trên máy mục tiêu, backup/restore, kiểm tra
  camera và quyền sử dụng model/dữ liệu.
