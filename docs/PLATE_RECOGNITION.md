.\.venv\Scripts# Nâng cấp nhận dạng biển số — M04 / NV-05, NV-07, NV-08

Ngày kiểm tra: 28/10/2026. Pipeline mặc định: ảnh xe → YOLO11s chuyên biển số
→ tối đa hai vùng/ảnh → Fast Plate OCR CCT-S v2 → tổng hợp toàn chuỗi qua nhiều ảnh.
Nhân viên vẫn xác nhận lượt vào/ra. Không sửa đoán `0/O`, `1/I`, `8/B`.

## Thay đổi và nguyên nhân

- Detector cũ chỉ dựa vào đường viền, có thể cắt nhầm thân xe hoặc bỏ sót biển.
  Detector mới dùng trọng số chuyên biển số, nạp lười trong worker, dùng lại giữa yêu cầu.
- Đọc tối đa hai vùng thay vì chỉ vùng đầu; OCR nhận PNG để tránh nén mất ký tự.
  Ảnh bằng chứng vẫn trả JPEG theo hợp đồng UI/lưu trữ hiện tại.
- Mỗi ảnh chỉ đóng góp tối đa một phiếu cho mỗi chuỗi; các vùng trong cùng ảnh
  không được tính thành nhiều khung độc lập. Nếu các chuỗi mâu thuẫn không có đa số,
  không tự điền biển. Giữ kết quả thô để đối chiếu.
- Fast Plate OCR chạy trong `.venv-alpr`, tách OpenCV headless khỏi Qt/OpenCV chính.
  PaddleOCR là lựa chọn dự phòng; đã sửa thứ tự hai dòng theo vị trí hình học và
  chỉ rõ đường dẫn model cục bộ. Không tải model trong lúc nhận diện.
- Ngưỡng OCR là điểm của model, **không phải tỷ lệ đọc đúng toàn bộ biển số**.

## Model và nguồn

- [YOLO11s plate detector](https://huggingface.co/morsetechlab/yolov11-license-plate-detection),
  revision `251a30d7daedca065f56e04b0af04052c907c68f`, file
  `license-plate-finetune-v1s.pt`, model card ghi AGPL-3.0. Tác giả cảnh báo bộ dữ
  liệu gốc trùng train/test; không dùng chỉ số của tác giả để chứng minh 90% ở đây.
- [Fast Plate OCR](https://github.com/ankandrew/fast-plate-ocr), package `1.1.0`,
  model `cct-s-v2-global-model`, cấu hình RGB 64×128, alphabet Latin, MIT theo
  repository. SHA-256 model và config được cố định trong `scripts/setup_plate_models.py`.
- YOLOv8 plate model của Koushim cũng được thử trong lúc so sánh nhưng không phải
  mặc định cuối. Trọng số thử nghiệm nằm trong thư mục model bị gitignore.

## Cài đặt và chạy lại

Ứng dụng chính vẫn dùng `.venv`; chỉ môi trường OCR mới cần cài thêm:

```powershell
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.venv-alpr'
uv sync --project environments/alpr --frozen
.\.venv\Scripts\python.exe scripts\setup_plate_models.py
.\.venv\Scripts\python.exe run_app.py
```

Lệnh setup tải model vào thư mục dự án và kiểm SHA-256, không ghi đè model có
hash khác. Runtime mặc định đã được cài và kiểm tra trên máy hiện tại.

| Biến môi trường | Mặc định |
|---|---|
| `PARKING_OCR_BACKEND` | `fast_plate`; có thể chọn `paddle` |
| `PARKING_PLATE_MODEL` | `models/license_plate_yolo11s.pt` |
| `PARKING_PLATE_IMAGE_SIZE` | `960` |
| `PARKING_PLATE_CONFIDENCE` | `0.15` |
| `PARKING_PLATE_DEVICE` | `cpu` |
| `PARKING_PLATE_MAX_REGIONS` | `2` |
| `PARKING_OCR_MAX_SAMPLES` | `5` |
| `PARKING_OCR_MIN_CONFIDENCE` | `0.6` |
| `PARKING_OCR_TIMEOUT_S` | `30`, giới hạn subprocess OCR |
| `PARKING_PLATE_OCR_MODEL` | `models/plate_ocr/cct_s_v2_global.onnx` |
| `PARKING_PLATE_OCR_CONFIG` | `models/plate_ocr/cct_s_v2_global_plate_config.yaml` |

`PARKING_OCR_PYTHON`, `PARKING_OCR_WORKER` ghi đè runtime/worker nếu cần.
Đổi backend phải khởi động lại ứng dụng. Thiếu model/runtime sẽ báo lỗi để nhập tay.

## Đo trên video người dùng

Nguồn: 11 MP4 trong thư mục `Source` do người dùng cung cấp, mỗi video khoảng
3–5 giây, 1280×720, ban ngày, xe máy đứng yên và camera di chuyển.

- Lấy ba khung cố định tại 20%, 50%, 80% mỗi clip.
- Chọn xe tiền cảnh bằng điểm chỉ định thủ công; crop xe bằng YOLOv8n. Không dùng
  biển OCR dự đoán để chọn xe. Nhãn được đọc trực quan, chưa được chủ dữ liệu xác nhận.
- 11 clip có 10 xe khác nhau, một xe được quay hai lần.
- Đây là **tập phát triển dùng để so sánh/chọn model**, không phải tập test độc lập.
  Chưa đo toàn chuỗi tracking/qua vạch; chưa đo precision/recall bbox vì chưa có bbox chuẩn.

| Cấu hình | Đúng toàn bộ biển/clip | Trung bình theo 10 xe |
|---|---:|---:|
| Dò đường viền + PaddleOCR, tổng hợp hiện tại | 1/11 (9,1%) | 5% |
| YOLO11s 640 + Fast Plate OCR | 10/11 (90,9%) | 90% |
| YOLO11s 960 + Fast Plate OCR | 11/11 (100%) | 100% |

Lượt đo cuối ở 960: trung bình 1,56 giây/clip, gồm nạp model ở yêu cầu đầu và
khởi động subprocess OCR mỗi yêu cầu; không phải FPS xử lý camera. Báo cáo JSON
ghi thời gian từng mẫu. Không coi kết quả này là bảo đảm >90% trên camera khác,
ban đêm, xe đang chạy hoặc ảnh bị che. Cần tập test mới, tách theo phiên quay/xe,
có nhãn được người dùng xác nhận trước khi nghiệm thu mục tiêu >90%.

Phép so sánh đường viền dùng `PARKING_OCR_BACKEND=paddle`,
`PARKING_PLATE_MAX_REGIONS=1` và `--heuristic`; vẫn dùng phần tổng hợp/chặn kết quả
mâu thuẫn đã sửa, nên không phải chạy lại nguyên trạng toàn bộ mã phiên bản trước.

Các ảnh, nhãn và báo cáo chứa dữ liệu người dùng chỉ nằm trong `.runtime/plate-review`
và `reports` (gitignored). Không đưa ảnh/biển thực vào bộ test mã nguồn.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_plates.py .runtime\plate-review\manifest.json --output reports\plate-evaluation-final.json
```

Manifest JSON gồm `scope` và `samples`; mỗi mẫu có `id`, `group` (cùng xe/phiên),
`plate` (nhãn đúng), `images` (danh sách đường dẫn ảnh xe tương đối với manifest),
`condition` (tùy chọn). Không đọc được, lỗi runtime hoặc không đề xuất đều tính sai
trong mẫu số. Công cụ báo cả độ phủ và độ chính xác trên các đề xuất, không dùng
hai chỉ số đó thay cho tỷ lệ đúng toàn bộ mẫu. Mã thoát 0 chỉ khi tỷ lệ trên manifest
đã cung cấp >90%; điều đó không chứng minh tính độc lập hay tính đại diện của dữ liệu.

## Kiểm chứng mã nguồn

- Toàn bộ pytest: **148 passed**, 86,39 giây; không mở camera hoặc sửa database vận hành.
- Ruff lint và format trên các file thay đổi: đạt.
- `scripts/check_ocr.py` với runtime mặc định: đọc đúng ảnh tổng hợp `51A12345`.
- Luồng UI xác nhận vào/ra, ảnh biển JPEG, audit và OCR bất đồng bộ được kiểm tra
  trong bộ acceptance. Model thật được kiểm tra bằng CLI trên manifest video ở trên.
