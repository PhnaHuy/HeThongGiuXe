# G5 — Đề xuất biển số và đối chiếu thủ công

G5 nối đề xuất qua vạch của G4 với vùng biển số, PaddleOCR, tra cứu và bằng chứng.
AI chỉ hỗ trợ nhân viên; không tự tạo lượt vào hoặc đóng lượt ra.

## Luồng đã triển khai

- `VideoWorker` giữ tối đa 5 ảnh crop phương tiện gần nhất cho mỗi track, lấy
  mẫu thưa để tránh lưu mọi khung hình; trạng thái bị xóa khi reset luồng hoặc
  track quá hạn.
- `PlateRegionDetector` đề xuất tối đa hai vùng hình chữ nhật theo biên, mật độ
  cạnh và tỷ lệ khung. Tỷ lệ hỗ trợ biển ngang và biển hai dòng; đây là bộ đề
  xuất heuristic OpenCV, chưa phải model detector biển số đã huấn luyện.
- `PlateRecognitionService` cắt vùng biển trên nhiều ảnh, gọi PaddleOCR và tổng
  hợp phiếu theo biển đã chuẩn hóa. Giữ nguyên chuỗi OCR thô; không tự đổi `0/O`
  hoặc `1/I`. Không tìm được vùng/chuỗi hợp lệ thì tiếp tục nhập tay.
- PaddleOCR chạy bằng tiến trình Python `.venv-ocr-313`, tách khỏi `cv2` của ứng dụng;
  backend fast-plate-ocr dùng `.venv-alpr`.
  IPC gửi JPEG trong stdin/stdout, giới hạn số lượng/kích thước ảnh và thời gian
  chờ; không ghi ảnh OCR tạm lên đĩa. PaddleOCR CPU chạy với oneDNN tắt theo
  lỗi runtime đã quan sát trên PaddlePaddle Windows.
- Khi duyệt sự kiện camera, biển đề xuất được điền vào form xe vào; với xe ra,
  chỉ lọc lượt đang gửi. Nhân viên vẫn tự chọn lượt, xem ảnh và xác nhận.
- Khi xác nhận, audit lưu OCR thô, biển đề xuất, độ tin cậy, biển được xác nhận
  hoặc biển của lượt được đối chiếu; ảnh cắt biển được lưu thành bằng chứng
  `PLATE_CROP`. Ảnh gốc vào/ra vẫn lưu như trước.
- OCR cũng có thể chạy với ảnh do nhân viên chọn. MP4 vẫn bị chặn khỏi giao dịch
  vận hành.

## Cấu hình và kiểm thử

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PARKING_OCR_BACKEND` | `fast_plate` | Backend `fast_plate` hoặc `paddle` |
| `PARKING_OCR_PYTHON` | `.venv-alpr` cho `fast_plate`; `.venv-ocr-313` cho `paddle` | Python cho backend đã chọn |
| `PARKING_OCR_WORKER` | `scripts\ocr_worker.py` | Tiến trình OCR cô lập |
| `PARKING_OCR_CACHE` | `.runtime\paddlex` | Cache model cục bộ |
| `PARKING_OCR_TIMEOUT_S` | `30` | Giới hạn thời gian một yêu cầu |
| `PARKING_OCR_MAX_SAMPLES` | `5` | Số crop tối đa mỗi lần tổng hợp |

Kiểm tra tích hợp trên ảnh tổng hợp:

```powershell
.\.venv\Scripts\python.exe scripts\check_ocr.py
```

Có thể truyền `--image <đường_dẫn_ảnh>` để thử một ảnh cục bộ. Ảnh/biển khách
hàng không được ghi vào repository. Model PaddleOCR phải có sẵn trong cache;
worker không tự tải model từ mạng.

Kiểm thử tự động:

- `tests/unit/test_plate_recognition.py`: vùng biển ngang/hai dòng, fusion nhiều
  ảnh, giữ nguyên ký tự OCR mơ hồ và xử lý không tìm thấy vùng.
- `tests/unit/test_paddle_ocr.py`: giao thức subprocess, marker JSON và timeout.
- `tests/acceptance/test_g5_scenarios.py`: OCR chỉ điền đề xuất; tạo/đóng lượt
  sau xác nhận; xe ra lọc nhưng không tự chọn; audit và ảnh crop được lưu.

## Bằng chứng chạy và giới hạn

- Kết quả OCR lịch sử trên máy kiểm thử: Python 3.11.15, PaddleOCR 3.7.0,
  PaddlePaddle 3.3.1, OpenCV 4.10.0.
- Cấu hình hiện tại dùng Python 3.13; các con số kiểm thử trên không xác nhận
  smoke test Python 3.13. Cần chạy lại theo `docs/G0_COMPATIBILITY.md`.
- Smoke test dùng ảnh tổng hợp với chuỗi `51A12345`: detector heuristic tìm vùng,
  PaddleOCR trả `51A12345` với confidence khoảng `0.9997`. Đây chỉ là kiểm tra
  kết nối API/model, không phải đánh giá độ chính xác OCR.
- Chưa có detector biển số chuyên dụng, bộ ảnh biển Việt Nam gán nhãn, ảnh biển
  hai dòng thực tế, video/camera bãi xe hoặc đo FPS/độ trễ đại diện. Vì vậy không
  kết luận G5 đạt chất lượng nhận diện ngoài thực tế. Để nghiệm thu cần đánh giá
  riêng tỷ lệ tìm đúng vùng, exact-match OCR, kết quả theo góc/ánh sáng/loại biển,
  latency và hiệu năng trên máy mục tiêu; sau đó quyết định có cần model detector
  riêng và dữ liệu huấn luyện hay không.
