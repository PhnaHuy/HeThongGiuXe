# G0 — Đối chiếu tương thích và cách tách môi trường

Ngày đối chiếu: 27/10/2026. Phạm vi: chuẩn bị Python 3.13 trên Windows x64 cho PySide6, OpenCV, YOLOv8n/ByteTrack và PaddleOCR. Tài liệu ghi quyết định chuẩn bị môi trường; kết quả chạy thực tế được ghi riêng trong báo cáo G0.

Ghi chú nâng cấp: các kết quả G0/G5/G8 ghi Python 3.11 là bằng chứng lịch sử,
không thay thế việc chạy lại test và smoke test trên Python 3.13. Phiên bản hiện
tại được khóa trong ba manifest và lockfile của dự án.

## 1. Quyết định dùng ba môi trường

G0 dùng ba môi trường Python 3.13 riêng, cùng nằm trong dự án:

| Môi trường | Thành phần | Gói cung cấp `cv2` |
|---|---|---|
| `.venv` | PySide6, SQLAlchemy, OpenCV, Ultralytics/YOLOv8n, ByteTrack, công cụ kiểm thử | `opencv-python` |
| `.venv-alpr` | fast-plate-ocr/ONNX Runtime | Không cài OpenCV |
| `.venv-ocr-313` | PaddleOCR 3.x, PaddlePaddle CPU và phụ thuộc OCR | `opencv-contrib-python` theo ràng buộc PaddleX |

Lý do là xung đột tên module giữa các wheel OpenCV, không phải thay đổi công nghệ dự án:

- Ultralytics khai báo phụ thuộc `opencv-python`. Metadata chính thức hiện loại trừ bản `4.13.0.90` và `torch==2.4.0` trên Windows. Tham khảo [pyproject.toml của Ultralytics](https://github.com/ultralytics/ultralytics/blob/main/pyproject.toml).
- Nhóm `ocr-core` của PaddleX dùng `opencv-contrib-python`; nguồn chính thức đang ràng buộc phiên bản `4.10.0.84`. Tham khảo [setup.py của PaddleX](https://github.com/PaddlePaddle/PaddleX/blob/develop/setup.py).
- Các wheel OpenCV dùng chung namespace `cv2`. Nhà phát hành yêu cầu chỉ cài một biến thể trong mỗi môi trường, kể cả khi các biến thể có cùng phiên bản. Tham khảo [OpenCV Python — Installation and Usage](https://pypi.org/project/opencv-python/).

Không sửa metadata của thư viện hoặc bỏ qua bộ giải phụ thuộc để ghép hai wheel vào một môi trường. Mỗi môi trường có manifest/lock riêng; danh sách phiên bản cài thực tế là căn cứ tái lập, không lấy nhánh `main`/`develop` của thư viện làm bản khóa.

Tại thời điểm G0, adapter OCR chưa được triển khai hoặc nghiệm thu; G5 sau đó đã thêm subprocess adapter tới `.venv-ocr-313`, với giới hạn thời gian, IPC rõ ràng và xử lý lỗi. Tích hợp này vẫn cần nghiệm thu trên máy mục tiêu. Ứng dụng chạy trên một máy, không cần server hoặc dịch vụ đám mây.

## 2. Căn cứ Windows/Python và baseline CPU

- Tài liệu Qt for Python yêu cầu Python 3.10 trở lên, khuyến nghị môi trường ảo; wheel PySide6 chứa sẵn Qt. Python 3.13 phù hợp yêu cầu phiên bản này. Tham khảo [Qt for Python — Getting Started](https://doc.qt.io/qtforpython-6/gettingstarted.html).
- Hướng dẫn PaddlePaddle Windows liệt kê Python 3.9–3.13, kiến trúc x64 và kiểm tra cài đặt bằng `paddle.utils.run_check()`. Hướng dẫn CPU hiện nêu PaddlePaddle 3.3.0. Đây là căn cứ chọn bản để thử, không chứng minh toàn bộ chuỗi OCR đã chạy trên máy đích. Tham khảo [hướng dẫn Windows trong repository chính thức PaddlePaddle](https://github.com/PaddlePaddle/docs/blob/develop/docs/install/pip/windows-pip_en.md).
- G0 dùng CPU làm baseline dù máy có GPU. Import, phép tính đơn giản và suy luận mẫu phải được kiểm tra thực; kiểm tra GPU/CUDA là kết quả riêng, không suy ra từ việc `nvidia-smi` có hiển thị GPU.
- Nếu import OpenCV trên Windows báo thiếu DLL, kiểm tra Visual C++ runtime theo [FAQ OpenCV](https://pypi.org/project/opencv-python/). Không tự cài lại CUDA hoặc thay thư viện khi chưa xác định nguyên nhân.

## 3. Chỉ cài OCR tối thiểu

Dùng gói `paddleocr` cơ bản và engine PaddlePaddle CPU riêng. Không cần `paddleocr[all]` cho thử đọc văn bản trên ảnh biển mẫu: nhóm `all` bổ sung phân tích tài liệu, hiểu tài liệu, dịch và trích xuất thông tin ngoài phạm vi G0. Nguồn: [PaddleOCR — Installation](https://www.paddleocr.ai/main/en/version3.x/installation.html).

Smoke test có thể chọn tường minh model `PP-OCRv5_mobile_det` và `PP-OCRv5_mobile_rec`, đặt `device="cpu"`, tắt nhận dạng hướng tài liệu, làm phẳng tài liệu và nhận dạng hướng dòng để giảm model không cần thiết. Các tên tham số `text_detection_model_name`, `text_recognition_model_name`, `text_detection_model_dir`, `text_recognition_model_dir`, `use_doc_orientation_classify`, `use_doc_unwarping` và `use_textline_orientation` có trong [API nguồn PaddleOCR 3.3](https://github.com/PaddlePaddle/PaddleOCR/blob/release/3.3/paddleocr/_pipelines/ocr.py). Phải kiểm tra lại với phiên bản đã khóa trước khi chạy.

Detector văn bản của PaddleOCR là bước tìm chữ trong ảnh đưa vào OCR; nó không thay thế detector xác định biển số trên ảnh phương tiện. Detector biển riêng và dữ liệu biển số Việt Nam vẫn là đầu vào cần chuẩn bị.

## 4. Model và cache cục bộ

Các biến cache phải được đặt trước khi import thư viện, bằng đường dẫn trong workspace; không thay đổi `HOME` của máy:

| Thành phần | Cấu hình | Căn cứ |
|---|---|---|
| Ultralytics | `YOLO_CONFIG_DIR` trỏ vào `.runtime`; truyền đường dẫn model local cho `YOLO(...)`. | [Ultralytics get_user_config_dir](https://docs.ultralytics.com/reference/utils/__init__/#ultralytics.utils.get_user_config_dir) |
| PaddleX | `PADDLE_PDX_CACHE_HOME` trỏ vào `.runtime/paddlex`. | [PaddleX cache.py](https://github.com/PaddlePaddle/PaddleX/blob/develop/paddlex/utils/cache.py) |
| Nguồn model OCR | Có thể chọn nguồn chính thức `PADDLE_PDX_MODEL_SOURCE=BOS`; sau khi tải, dùng đường dẫn model local để chạy lại. | [PaddleOCR FAQ](https://www.paddleocr.ai/main/en/FAQ.html) |

YOLOv8n là model phát hiện phương tiện baseline được mô tả trong [tài liệu YOLOv8](https://docs.ultralytics.com/models/yolov8/). Bộ tải chính thức lấy `yolov8n.pt` từ repository `ultralytics/assets`; nguồn hiện có release mặc định `v8.4.0`. Khi tải cần ghi URL cuối cùng, kích thước, SHA-256 và vị trí lưu, không coi tên tệp là bằng chứng nguồn gốc. Căn cứ: [mã tải asset chính thức](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/utils/downloads.py).

Ghi nhận điều kiện AGPL-3.0/Enterprise của Ultralytics trong danh mục model; không tuyên bố bản đồ án đã đủ quyền phân phối thương mại. Tham khảo [giấy phép Ultralytics](https://www.ultralytics.com/license). Không đưa trọng số lớn hoặc dữ liệu khách hàng vào Git.

## 5. Giới hạn kết luận

G0 chỉ xác nhận những phép thử đã chạy thành công. Import thư viện không chứng minh suy luận; suy luận trên ảnh tổng hợp không chứng minh đọc biển số thực tế; tracking trên hình không có xe không chứng minh đếm xe chính xác. Chất lượng nhận dạng, góc camera, biển hai dòng, hiệu năng toàn chuỗi và giao tiếp giữa hai môi trường phải được kiểm chứng ở các giai đoạn tương ứng.
