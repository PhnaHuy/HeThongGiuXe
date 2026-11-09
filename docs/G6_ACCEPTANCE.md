# Nghiệm thu G6 — Quản lý và giám sát

## Phạm vi

G6 hoàn thiện các lát cắt quản trị/supervision đã có nền từ G1–G5: tài khoản và
vai trò, hồ sơ khách/xe, sức chứa, tổng quan, thống kê, lịch sử, ngoại lệ và audit.
Không bao gồm giám sát polygon ô đỗ hay sức chứa theo từng khu; các phần đó cần
mô hình khu/ô đỗ của G7.

## Kết quả theo yêu cầu

| Story | Kết quả |
|---|---|
| QL-01 | Tab tổng quan dành cho quản lý/quản trị hiển thị tổng lượt mở, số lượng theo loại, chỗ còn và thời điểm làm mới. Tự làm mới mỗi 30 giây; thao tác xác nhận vào/ra làm mới ngay. |
| QL-03 | Thống kê lượt vào và lượt ra theo khoảng ngày; các bộ đếm lấy từ thời điểm vào/ra thực tế và có phân loại xe máy/ô tô. Tra cứu lịch sử hiện có lọc biển/mã lượt, khách, loại, trạng thái và ngày, xem ảnh vào/ra. |
| QL-04 | Danh sách bất thường lọc chưa/đã xử lý; gồm lượt được nhân viên gắn cờ, xe ra không tìm thấy lượt, và sai khác OCR/loại xe có audit. Có ảnh khả dụng, kết quả/lý do, nhân viên. Quản lý ghi chú và xử lý; lịch sử gốc được giữ. |
| QT-01 | Quản trị viên tạo tài khoản và gán vai trò, khóa/mở khóa; các tab và use case nhạy cảm kiểm tra vai trò. |
| QT-04 | Quản trị viên lưu sức chứa xe máy/ô tô không âm; tổng sức chứa là tổng hai nhóm. Bản ghi cấu hình là bổ sung, không phá hủy database cũ; thay đổi được audit và cập nhật lên màn hình vận hành. |
| QT-05 | Quản trị viên tìm khách bằng tên/biển số, sửa hồ sơ hoặc biển/loại xe. Trùng biển bị từ chối, lượt cũ giữ snapshot và thay đổi được ghi trước/sau. |
| QT-06 | Quản lý/quản trị tra cứu audit theo ID tài khoản, hành động và khoảng ngày; không có thao tác sửa/xóa nhật ký. |

## Kiểm thử

Kiểm thử tích hợp/acceptance được bổ sung trong:

- `tests/integration/test_g6_management.py`
- `tests/acceptance/test_g6_scenarios.py`

Chạy tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

Kết quả kiểm tra G6: **112 test đạt** trên toàn bộ suite; `ruff check .` đạt;
kiểm tra format đạt cho 19 tệp Python thay đổi. Lệnh format toàn repo còn báo
một tệp cũ ngoài phạm vi G6 (`tests/acceptance/test_app_lifecycle.py`) cần format;
tệp này không được chỉnh trong thay đổi G6.

## Giới hạn còn lại

- Sức chứa hiện lưu theo loại xe và tổng toàn bãi; chưa có phân khu hay cấu hình
  sức chứa theo từng khu vì chưa có model khu vực.
- Dashboard đếm lượt mở từ database. Số xe quan sát từ từng ô chưa được hiển thị;
  phần đó thuộc G7 và phải tách biệt với số lượt.
- Thống kê là bộ đếm nghiệp vụ, chưa có biểu đồ hoặc xuất báo cáo.
- Phần kiểm thử dùng SQLite/fixture cục bộ; không chứng minh quyền truy cập đa
  người dùng trên máy triển khai hoặc hiệu năng với dữ liệu vận hành lớn.
