# G4 — Phát hiện và theo dõi phương tiện

Story/module: NV-02, NV-05, NV-07, QT-03, CM-01; M02, M03, M06, M08, M09.

## Đã triển khai

- Dùng trọng số YOLOv8n local và ByteTrack có sẵn trong Ultralytics; lọc lớp
  COCO `car`/`motorcycle`, hiển thị bounding box, loại xe, confidence và track ID.
- Suy luận chạy trong `VideoWorker`, không chạy trên GUI thread. Lỗi thiếu model,
  lỗi nạp model hoặc lỗi suy luận được báo trạng thái rõ ràng; ứng dụng không tự
  tải trọng số từ mạng.
- Bộ kiểm tra vạch dùng tọa độ chuẩn hóa của centroid, deadband, số khung ổn định,
  hướng VÀO cấu hình trên từng nguồn và chống lặp theo track/hướng trong phiên.
- Đổi nguồn, kết nối lại hoặc tua reset tracker, trạng thái qua vạch và ID luồng.
- Sự kiện chỉ là `EventCandidate`, có ảnh crop phương tiện, loại xe, confidence,
  track, nguồn và thời gian quan sát/media. Sự kiện không tự ghi database.
- Camera trực tiếp có thể chuyển ảnh vào form xác nhận xe vào hoặc xe ra. Nhân
  viên vẫn phải nhập/đối chiếu biển; xe ra phải chọn đúng lượt đang mở trước khi
  xác nhận.
- MP4 hiển thị phát hiện/sự kiện và cho chuyển đề xuất sang luồng xác nhận
  vào/ra như camera, lưu lượt sau khi người dùng kiểm tra và xác nhận.

## Cấu hình mặc định

Model mặc định: `models/yolov8n.pt`; thiết bị suy luận mặc định là CPU. Có thể
ghi đè bằng biến môi trường sau (đọc lại khi khởi động ứng dụng):

| Biến | Mặc định | Ý nghĩa |
|---|---:|---|
| `PARKING_VISION_MODEL` | `models/yolov8n.pt` | Đường dẫn checkpoint local |
| `PARKING_VISION_CONFIDENCE` | `0.25` | Ngưỡng phát hiện |
| `PARKING_VISION_IMAGE_SIZE` | `640` | Kích thước suy luận YOLO |
| `PARKING_VISION_DEVICE` | `cpu` | Thiết bị PyTorch/Ultralytics |
| `PARKING_CROSSING_DEADBAND` | `0.015` | Khoảng cách chuẩn hóa bỏ vùng sát vạch |
| `PARKING_CROSSING_STABLE_FRAMES` | `2` | Số quan sát liên tiếp xác nhận một phía |
| `PARKING_TRACK_STALE_FRAMES` | `300` | Số khung giữ trạng thái track vắng mặt |

Để có đề xuất qua vạch, admin cần chọn đúng camera và lưu một `GateLine`. Tọa độ
vạch được chuẩn hóa theo vùng hình hiển thị; phía VÀO theo mũi tên đã cấu hình.
Nếu không có vạch, ứng dụng vẫn vẽ phát hiện nhưng không sinh sự kiện VÀO/RA.

## Kiểm chứng tự động

- `tests/unit/test_gate_crossing.py`: hai hướng qua vạch, chiều VÀO đảo được,
  chống rung, bỏ phát hiện không có track ID, chống lặp và reset phiên.
- `tests/unit/test_yolo_detector.py`: ánh xạ lớp/box, tham số ByteTrack và từ chối
  model local bị thiếu.
- `tests/acceptance/test_g4_scenarios.py`: video giả lập đi qua vạch tạo đúng
  một sự kiện có ảnh crop; camera trực tiếp chuyển sang form nhưng chưa tự tạo
  lượt; xe ra yêu cầu chọn lượt và xác nhận; MP4 chuyển được đề xuất; lỗi model
  hiển thị rõ và không mở nguồn.
- `tests/acceptance/test_g3_scenarios.py`: kiểm tra lại các luồng nguồn/MP4 G3
  bằng detector giả lập để cô lập kiểm thử vòng đời video khỏi tải model.

## Giới hạn nghiệm thu

Các bài test sự kiện qua vạch dùng detector giả lập và hình/video tổng hợp. Model
YOLOv8n được smoke-test riêng ở G0 trên CPU, nhưng mẫu tổng hợp đó không chứa xe
thực và không đo độ chính xác phát hiện. Chưa có video bãi xe được gán nhãn để
đánh giá tỷ lệ phát hiện, phân loại, đếm thừa/bỏ sót, FPS, độ trễ hoặc tải phần
cứng. Camera/RTSP tại bãi cũng chưa được kiểm tra. Vì vậy không tuyên bố G4 đạt
chỉ tiêu độ chính xác hay hiệu năng thực tế.

Detector G4 phân loại xe máy/ô tô theo COCO. Detector biển số, OCR, tổng hợp
multi-frame, tra hồ sơ và đề xuất biển số thuộc G5. Vùng polygon ô đỗ thuộc G7.
