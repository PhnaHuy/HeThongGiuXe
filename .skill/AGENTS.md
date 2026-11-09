# Quy tắc triển khai dự án quản lý bãi giữ xe bằng thị giác máy tính

> **Phạm vi áp dụng:** toàn bộ mã nguồn, cấu hình, dữ liệu mẫu, tài liệu và kiểm thử trong repository này. Đặt file này tại thư mục gốc dự án để AI lập trình đọc trước khi sửa mã.  
> **Nguồn yêu cầu:** `de_tai_quan_ly_bai_giu_xe_thi_giac_may_tinh.md` (ý tưởng, 28 user story, 10 module). Nếu tài liệu nguồn chưa có trong repository, yêu cầu người dùng cung cấp hoặc dùng bản đã được chia sẻ trong phiên làm việc; không tự bịa điều kiện chấp nhận.  
> **Mục tiêu:** phần mềm chạy trên một máy tại bãi xe, nhận camera trực tiếp hoặc MP4, nhận dạng xe/biển số, tra cứu khách hàng và hỗ trợ nhân viên xác nhận lượt vào/ra.

## 1. Cách sử dụng file này

1. Đọc file này và tài liệu yêu cầu trước khi lập kế hoạch, viết mã hoặc thay đổi kiến trúc.
2. Khi thực hiện một chức năng, ghi rõ mã user story (`NV-05`, `QT-03`...) và module (`M06`, `M02`...) liên quan trong mô tả công việc/PR.
3. Xem các mục **BẮT BUỘC** là điều kiện nghiệm thu dự án. Nếu yêu cầu mới mâu thuẫn, nêu rõ điểm mâu thuẫn và đề xuất thay đổi nhất quán với yêu cầu mới; không âm thầm bỏ quy tắc.
4. Chỉ tuyên bố tính năng hoàn thành khi có bằng chứng chạy được và đạt các điều kiện chấp nhận tương ứng.
5. Quy tắc trong file này không thay thế các chỉ dẫn có mức ưu tiên cao hơn của môi trường làm việc hay yêu cầu mới được người dùng xác nhận.

## 2. Phạm vi và bất biến nghiệp vụ

### 2.1. BẮT BUỘC

- Hỗ trợ hai nguồn: **camera trực tiếp** và **MP4**. MP4 mặc định là chế độ thử nghiệm, không tạo/đóng lượt gửi xe vận hành; mọi ngoại lệ phải là thao tác chủ động, rõ ràng của người có quyền.
- AI chỉ **đề xuất** loại xe, biển số và sự kiện qua cổng. Nhân viên phải xác nhận trước khi tạo lượt vào hoặc đóng lượt ra.
- Biển số giúp **tra cứu** hồ sơ/lượt xe; không coi biển số là bằng chứng duy nhất để tự động cho xe ra.
- Không suy đoán tên, số điện thoại hoặc danh tính khách hàng chỉ từ ảnh/biển số. Chỉ hiển thị thông tin hồ sơ đã đăng ký.
- Chấp nhận khách vãng lai. Nếu biển số chưa đăng ký, nhân viên vẫn tạo được lượt có mã lượt, ảnh, giờ vào và loại xe sau khi kiểm tra.
- Một lượt có trạng thái chính `DANG_GUI` hoặc `DA_RA`; cờ `CAN_XU_LY` không tự đóng lượt. Một lượt đã `DA_RA` không thể đóng lần thứ hai.
- Không tạo hai lượt đang mở cho cùng biển số đã được chuẩn hóa mà không có quy trình xử lý ngoại lệ rõ ràng. Lượt không đọc được biển số phải có **mã lượt riêng** để đối chiếu thủ công.
- Trước khi đóng lượt, hiển thị ảnh lúc vào, ảnh lúc ra, biển số, loại xe và cảnh báo sai lệch để nhân viên đối chiếu.
- Lưu thông tin biển số/loại xe **đã xác nhận tại thời điểm giao dịch** trong lượt; sửa hồ sơ phương tiện sau này không thay đổi lịch sử cũ.
- Mọi chỉnh sửa OCR, loại xe, quyết định ngoại lệ và xác nhận xe vào/ra phải có tài khoản, thời gian và giá trị trước/sau khi áp dụng.
- Hiển thị `KHONG_XAC_DINH` khi camera khu đỗ mất kết nối hoặc không đủ bằng chứng; không coi ảnh cũ là trạng thái ô trống.
- Tính số xe đang gửi từ **lượt đang mở**. Số ô camera nhìn thấy có xe là phép đo khác; không âm thầm thay một số cho số kia.

### 2.2. Ngoài phạm vi bản đầu

- Không tự mở barie, tự trả xe, tự thu tiền hoặc nhận diện chủ xe bằng khuôn mặt.
- Không xây ứng dụng riêng để khách hàng đăng nhập khi chưa có yêu cầu mới.
- Không cam kết FPS hoặc tỷ lệ OCR cụ thể trước khi đo trên camera, ánh sáng và phần cứng thực tế.
- Không thêm microservice, hàng đợi phân tán, đám mây hoặc cơ sở dữ liệu máy chủ cho bản chạy một máy nếu chưa có nhu cầu rõ.

## 3. Công nghệ và framework được chọn

| Thành phần | Mặc định triển khai | Quy tắc |
|---|---|---|
| Ngôn ngữ | Python 3.11 trong môi trường ảo riêng | Kiểm tra tương thích toàn bộ thư viện trước khi nâng phiên bản; không phụ thuộc Python 3.14 trên máy người dùng nếu OCR chưa được xác nhận hỗ trợ. |
| Giao diện desktop | PySide6 (Qt for Python) | GUI chạy trên main thread; đọc video/suy luận chạy ở worker, cập nhật màn hình qua signal/slot. |
| Video và xử lý ảnh | OpenCV | Đóng `VideoCapture` và tài nguyên khi dừng/chuyển nguồn; phân biệt hết MP4 với lỗi camera. |
| Phát hiện phương tiện | Ultralytics YOLOv8n cho baseline | Model được cấu hình bằng đường dẫn/tên; không hardcode vào logic nghiệp vụ; chỉ thay model sau đo đạc. |
| Theo dõi | ByteTrack cấu hình rõ ràng | Giữ trạng thái chỉ trong một luồng liên tục; reset tracker khi đổi camera/video hoặc tua MP4. |
| Biển số | Detector biển số riêng + OCR (ưu tiên khảo sát PaddleOCR 3.x) | Không dùng giả định YOLOv8 nhận xe là đã nhận biển; kiểm thử OCR trên biển số Việt Nam. |
| Cơ sở dữ liệu | SQLite + SQLAlchemy 2.x | Giao dịch vào/ra có transaction; không truy cập SQL trực tiếp từ widget GUI. |
| Kiểm thử và chất lượng | pytest, Ruff, định dạng mã nhất quán | Khóa phiên bản phụ thuộc sau khi thử cài/chạy trên Windows và lưu manifest phụ thuộc. |

**Quyết định kiến trúc:** ưu tiên ứng dụng desktop chạy trên một máy. Không mặc định thêm FastAPI/React hoặc server từ xa. Nếu yêu cầu nhiều máy, hãy đề xuất bản mở rộng riêng và đánh giá lại quyền truy cập, đồng bộ lượt và cơ sở dữ liệu.

**Tương thích môi trường:** kiểm tra phiên bản Python, hệ điều hành, CPU/GPU và khả năng cài PaddlePaddle/PaddleOCR **trước** khi viết mã phụ thuộc vào chúng. Nếu OCR đề xuất không cài được trên máy đích, giữ giao diện `PlateRecognizer` và thay adapter phù hợp; không xóa chức năng xác nhận biển số thủ công. Với GPU, chỉ cấu hình CUDA sau khi biết chính xác phần cứng và phiên bản driver; CPU là baseline hoạt động.

**Giấy phép:** trước khi phân phối thương mại, kiểm tra điều kiện giấy phép Ultralytics YOLOv8 và các model/trọng số, dữ liệu huấn luyện, font và thư viện dùng kèm. Không trình bày bản đồ án như sản phẩm thương mại đã được cấp quyền.

## 4. Ranh giới 10 module

Giữ luồng phụ thuộc một chiều: `UI → application/use_cases → domain` và `infrastructure` triển khai các giao diện mà application cần. Không cho domain import PySide6, OpenCV, Ultralytics hoặc SQLAlchemy.

| Module | Trách nhiệm và ranh giới |
|---|---|
| M01 — Tài khoản và phân quyền | Đăng nhập, vai trò, kiểm tra quyền; không nhúng quyền bằng các nút GUI đơn thuần. |
| M02 — Nguồn hình/cấu hình camera | Camera, MP4, trạng thái kết nối, vạch và vùng ô; không tự tạo giao dịch gửi xe. |
| M03 — Phát hiện/theo dõi xe | Bounding box, loại xe, track ID tạm thời, hướng qua vạch, chống đếm lặp; phát `EventCandidate`. |
| M04 — Nhận dạng biển số | Chọn ảnh rõ, phát hiện biển, OCR, chuẩn hóa và độ tin cậy; không tự gắn khách hàng. |
| M05 — Khách hàng/phương tiện | Hồ sơ khách, nhiều xe/khách, kiểm tra trùng biển, tra cứu; không sửa lịch sử lượt cũ. |
| M06 — Lượt gửi xe | Tạo/đóng lượt trong transaction, trạng thái và quy tắc chống trùng; chỉ nhận lệnh sau xác nhận hợp lệ. |
| M07 — Sức chứa/ô đỗ | Tính lượt mở, chỗ còn, trạng thái ô, chênh lệch hai số đo; không tự đóng lượt. |
| M08 — Xác nhận/ngoại lệ | Màn hình quyết định, sửa OCR/loại xe, tìm lượt thủ công, lý do và dấu vết. |
| M09 — Giám sát/tra cứu/thống kê | Trình bày luồng, bộ lọc, tổng hợp dữ liệu; không chứa quy tắc nghiệp vụ cốt lõi. |
| M10 — Bằng chứng/nhật ký | Ảnh vào/ra, snapshot dữ liệu, lịch sử sửa và lỗi lưu; không để ảnh chỉ nằm trong RAM. |

### 4.1. Cấu trúc repository đề xuất

```text
project/
├── AGENTS.md
├── de_tai_quan_ly_bai_giu_xe_thi_giac_may_tinh.md
├── pyproject.toml
├── src/parking_app/
│   ├── domain/              # Entity, enum, quy tắc bất biến
│   ├── application/         # Use case, DTO, interface/port
│   ├── infrastructure/
│   │   ├── video/           # Camera, MP4, đồng hồ nguồn hình
│   │   ├── vision/          # YOLO, tracker, detector biển, OCR
│   │   ├── persistence/     # SQLAlchemy, SQLite, transaction
│   │   └── evidence/        # Lưu ảnh bằng chứng
│   ├── ui/                  # PySide6: màn hình, view model, worker
│   └── config/              # Cấu hình và kiểm tra môi trường
├── tests/
│   ├── unit/
│   ├── integration/
│   └── acceptance/
└── sample_data/             # Dữ liệu demo được phép chia sẻ
```

- Chỉ tạo thư mục khi có mã thực sự cần đặt vào; tránh lớp trừu tượng rỗng.
- Không commit video/ảnh khách hàng thật, tệp database vận hành, mật khẩu camera hoặc model trọng số không có quyền chia sẻ.
- Cấu hình và đường dẫn model/ảnh/database phải đặt ngoài mã nguồn bằng file cấu hình mẫu và biến môi trường phù hợp; không hardcode đường dẫn `C:\Users\...`.

## 5. Hợp đồng dữ liệu và luồng hình

### 5.1. Kiểu dữ liệu tối thiểu

- `Frame`: `source_id`, `source_kind` (`LIVE`/`MP4`), `frame_index`, thời gian khung hình, ảnh; không trộn thời gian khung hình với thời điểm nhân viên xác nhận.
- `VehicleDetection`: khung bao, nhãn loại xe, độ tin cậy, `track_id` tạm thời.
- `EventCandidate`: camera, hướng vào/ra, ảnh xe/biển, loại xe, OCR đề xuất, thời điểm quan sát, trạng thái chờ xác nhận.
- `Customer`: mã khách, tên, liên hệ; `Vehicle`: mã xe, biển số chuẩn hóa, biển hiển thị, loại xe, mã khách.
- `ParkingSession`: mã lượt, biển/loại xe **snapshot**, khách/xe liên quan nếu có, giờ vào, giờ ra, trạng thái, ảnh liên kết, nhân viên xác nhận.
- `Evidence`: mã ảnh, loại ảnh, mã lượt, đường dẫn, thời điểm; `AuditEntry`: tài khoản, hành động, thời điểm, giá trị trước/sau, lý do.

### 5.2. Quy tắc nguồn hình và thời gian thực

1. Dùng `VideoSource` interface cho camera và MP4; cùng pipeline thị giác, khác chính sách phát khung hình/ghi dữ liệu.
2. Không chặn main thread PySide6 bằng đọc camera, OCR, suy luận hoặc ghi video. Dùng worker và signal/slot; dừng worker sạch khi đổi nguồn/đóng ứng dụng.
3. Camera trực tiếp ưu tiên độ trễ thấp: hàng đợi khung hình có giới hạn, có thể bỏ khung cũ **để hiển thị/suy luận**, nhưng không được âm thầm khẳng định đã xử lý đầy đủ các sự kiện bị bỏ lỡ. Báo trạng thái quá tải.
4. MP4 đánh giá thuật toán phải cho phép chạy xác định, không bỏ khung do UI; phân biệt chế độ phát theo thời gian thực và chế độ xử lý hết video.
5. Dùng thời gian/khung hình video cho đánh giá trên MP4; lưu thời điểm thực tế xác nhận riêng trong chế độ live.
6. Reset trạng thái tracker, vạch đã đếm và bộ tổng hợp OCR khi đổi nguồn hoặc tua video. Không mang ID từ camera này sang camera khác.
7. Chỉ tạo sự kiện qua vạch khi track đi qua đúng hướng và đủ ổn định. Cùng một lần qua vạch phải được chống trùng theo nguồn, track và lần đi qua; không dùng mỗi một frame làm căn cứ.

### 5.3. Quy tắc OCR và đối chiếu

- Không coi độ tin cậy YOLO của xe là độ tin cậy OCR biển số.
- Giữ ảnh gốc, vùng biển cắt, kết quả OCR thô và kết quả đã được nhân viên xác nhận (nếu có).
- Chuẩn hóa an toàn để tra cứu: viết hoa, bỏ khoảng trắng/dấu phân cách trình bày; không tự thay `0/O`, `1/I` hoặc thêm ký tự để làm biển số “hợp lệ”.
- Dùng nhiều khung hình cùng xe để chọn/đối chiếu kết quả; nếu mâu thuẫn hoặc không đọc được thì chuyển cho nhân viên.
- Cho nhân viên tìm lượt theo biển nhập tay, thời gian, loại xe và ảnh; không ghép lượt bằng suy đoán khi thiếu bằng chứng.

## 6. Dữ liệu, giao dịch và quyền riêng tư

1. Bật khóa ngoại SQLite, tạo ràng buộc dữ liệu và index cần thiết. Ghi lượt, trạng thái và nhật ký trong transaction; lỗi thì rollback, báo cho nhân viên, không hiển thị là đã thành công.
2. Kiểm tra biển số trùng sau chuẩn hóa. Chặn trùng lượt đang mở bằng ràng buộc và kiểm tra trong nghiệp vụ; với biển số chưa biết dùng mã lượt duy nhất.
3. Không xóa lịch sử để “sửa” lượt cũ. Chỉnh sửa có quyền, lý do và audit; lưu snapshot giá trị tại thời điểm giao dịch.
4. Ảnh phải gắn với mã lượt và loại sự kiện; tên file an toàn, không dùng nguyên biển số/tên khách làm đường dẫn. Xử lý lỗi lưu ảnh hoặc dữ liệu một cách rõ ràng, tránh lượt có tham chiếu ảnh không tồn tại.
5. Lưu tối thiểu dữ liệu khách cần cho nghiệp vụ; hạn chế quyền xem số điện thoại/ảnh. Cung cấp cấu hình lưu giữ và sao lưu theo yêu cầu vận hành thực tế, không tự đặt thời hạn pháp lý khi chưa xác minh.
6. Mật khẩu được băm bằng cơ chế phù hợp; không lưu mật khẩu dạng rõ. URL camera và thông tin nhạy cảm không xuất hiện trong log, ảnh chụp màn hình demo hay repository.
7. Dữ liệu mẫu dùng cho kiểm thử phải là dữ liệu được phép dùng hoặc đã ẩn thông tin nhận dạng; không dùng ảnh/biển số thật của khách để commit lên Git.

## 7. Clean code và chất lượng triển khai

### 7.1. BẮT BUỘC khi viết mã

- Mỗi hàm/lớp có một trách nhiệm rõ. UI chỉ hiển thị và nhận thao tác; use case điều phối; domain giữ quy tắc; adapter giao tiếp thư viện/thiết bị.
- Dùng type hints ở public interface, tên hàm/biến rõ nghĩa bằng tiếng Anh; nội dung giao diện và tài liệu người dùng bằng tiếng Việt. Tránh viết tắt khó hiểu và magic number.
- Tham số ngưỡng OCR, độ ổn định ô, kích thước frame, thời gian chờ và sức chứa ở cấu hình có giá trị mặc định, kiểm tra hợp lệ; ghi rõ đơn vị.
- Không nhân bản logic chuẩn hóa biển, tính số xe, chuyển trạng thái lượt ở nhiều màn hình/module.
- Không dùng `except:` trống, bỏ qua lỗi lưu dữ liệu hay khởi động camera. Log có ngữ cảnh (source ID, session ID) nhưng không lộ thông tin nhạy cảm.
- Không trộn trực tiếp OpenCV BGR/numpy array với Qt widget ở mọi nơi; chuyển đổi qua một adapter UI có kiểm soát vòng đời bộ nhớ.
- Không tạo side effect trong hàm phân tích frame. Tách `predict`/đề xuất khỏi `confirm_entry`/`confirm_exit`.
- Không ghi cứng `model.track(..., persist=True)` qua các nguồn không liên tục; tạo một tracker theo từng luồng và reset đúng lúc.
- Dùng enum/constant cho trạng thái, hướng, loại xe và vai trò; không dùng chuỗi tự do rải rác.
- Ghi chú giải thích **vì sao** có quy tắc khó (chống trùng, reset tracker, snapshot lượt); tránh comment chép lại từng dòng mã.

### 7.2. Phụ thuộc và thay đổi thiết kế

- Dùng `pyproject.toml` để khai báo phụ thuộc và cấu hình công cụ. Sau khi cài thử trên Windows, khóa phiên bản phụ thuộc tái lập được; không tự nâng major version giữa chừng.
- Không đưa framework mới vào chỉ vì tiện một màn hình. Mọi thay đổi framework, cơ sở dữ liệu hoặc model phải nêu lợi ích, chi phí, tác động tới 10 module và cách kiểm chứng.
- Không sửa file dữ liệu/model đã huấn luyện như một phần của refactor mã nguồn mà không lưu provenance và kết quả đánh giá trước/sau.

### 7.3. Thay đổi và thêm mới
- Khi có bất kỳ thay đổi và thêm mới chức năng phải phân tích và hỏi để xác nhận.
- Khi muốn thay đổi công nghệ phải đưa ra 2 giải giải pháp để chọn

## 8. Kiểm thử, nghiệm thu và hiệu năng

### 8.1. Cổng kiểm tra bắt buộc

Trước khi đánh dấu một user story hoàn thành:

1. Chỉ rõ ID story và từng điều kiện chấp nhận đã thực hiện.
2. Chạy lint/format, unit test cho quy tắc nghiệp vụ và integration test cho luồng dữ liệu bị ảnh hưởng.
3. Chạy ít nhất một luồng thao tác có ý nghĩa qua UI/CLI kiểm thử, với ảnh/video được phép dùng hoặc fixture, khi thay đổi phần camera/AI/nghiệp vụ.
4. Kiểm tra lỗi biên tương ứng: mất camera, hết MP4, OCR sai, biển chưa đăng ký, cùng biển có lượt mở, đóng lượt hai lần, lỗi lưu ảnh/database.
5. Báo cáo kết quả đo được, hạn chế còn lại và môi trường thử; không ghi “realtime” hoặc “đọc chính xác” nếu chưa có phép đo.

### 8.2. Bộ kiểm thử cốt lõi

| Nhóm | Trường hợp tối thiểu |
|---|---|
| Vào/ra | Lượt hợp lệ; một lần qua vạch không đếm đôi; xe ra đóng đúng lượt; không đóng hai lần. |
| Hồ sơ/biển | Nhiều xe cho một khách; biển trùng hồ sơ; chuẩn hóa không tự sửa ký tự; khách vãng lai. |
| Nhận dạng/ngoại lệ | OCR sai được sửa; OCR không đọc được; loại xe khác đăng ký; xe ra không tìm lượt. |
| Nguồn hình | Camera mất/kết nối lại; MP4 hết; đổi/tua nguồn reset tracker; MP4 không ghi dữ liệu thật. |
| Dữ liệu | Lỗi ghi transaction rollback; ảnh gắn đúng lượt; sửa hồ sơ không thay lịch sử; audit có người và giá trị trước/sau. |
| Sức chứa | Vào/ra cập nhật số lượt mở; đầy bãi; mất camera ô đỗ chuyển không xác định. |

### 8.3. Đánh giá mô hình trên dữ liệu chưa dùng để tinh chỉnh

- Tách train/validation/test theo **video hoặc phiên quay**, tránh khung hình gần nhau của cùng xe xuất hiện ở cả tập train và test.
- Báo cáo độ chính xác đếm sự kiện vào/ra, tỷ lệ đúng loại xe, tỷ lệ đúng **toàn bộ** biển số, số lần phải sửa tay, độ chính xác ô đỗ (nếu có).
- Đo FPS xử lý, độ trễ đến khi hiện đề xuất, mức dùng CPU/GPU và số khung hình bị bỏ trên máy trình diễn; ghi độ phân giải, số camera và model.
- Đánh giá riêng ban ngày/ban đêm, biển nghiêng, xe đi sát nhau, che khuất, ảnh mờ; không lấy kết quả video đẹp làm kết quả chung.

## 9. Quy trình làm việc của AI (project skill)

Khi người dùng yêu cầu triển khai một phần của dự án, thực hiện lần lượt:

1. **Đọc và đối chiếu:** đọc `AGENTS.md`, tài liệu yêu cầu và cấu trúc mã hiện có; xác định story, module, trạng thái dữ liệu và luồng hình liên quan.
2. **Nêu kết quả mong đợi:** viết ngắn đầu vào, đầu ra, điều kiện chấp nhận và những trường hợp lỗi. Với điểm chưa được chốt, chọn giải pháp tối thiểu nhất quán hoặc hỏi khi quyết định đó làm thay đổi nghiệp vụ.
3. **Thiết kế lát cắt dọc:** sửa đủ domain → use case → adapter → UI để có một luồng chạy được; không tạo hàng loạt lớp placeholder.
4. **Cài đặt:** bảo vệ bất biến tại tầng nghiệp vụ và database; giữ giao diện AI/nguồn hình có thể thay thế; không để UI tự ghi database.
5. **Kiểm chứng:** chạy kiểm thử liên quan, kiểm tra thủ công với dữ liệu mẫu, đo hiệu năng khi có thay đổi pipeline; sửa lỗi phát hiện được.
6. **Bàn giao:** nêu file đã đổi, story/AC đã đạt, cách chạy, kết quả kiểm thử, giới hạn còn lại; phân biệt rõ phần đã làm với phần mới đề xuất.

### Mẫu báo cáo hoàn thành một chức năng

```text
Story/module: NV-07 / M06, M08, M10
Đã làm: ...
Điều kiện chấp nhận: 1) ... đạt; 2) ... đạt; 3) ... đạt
Kiểm thử: lệnh/chế độ, dữ liệu mẫu, kết quả
Giới hạn hoặc vấn đề còn lại: ...
```

## 10. Tài liệu chính thức để kiểm tra khi thay đổi thư viện

- [Qt for Python — signal/slot và thread](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html)
- [OpenCV — VideoCapture](https://docs.opencv.org/doc/doxygen/html/d8/dfe/classcv_1_1VideoCapture.html)
- [Ultralytics — YOLOv8 và giấy phép](https://docs.ultralytics.com/models/yolov8)
- [Ultralytics — Tracking](https://docs.ultralytics.com/modes/track)
- [PaddleOCR — Installation](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/installation.html)
- [SQLAlchemy 2.0 — Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
- [pytest — Documentation](https://docs.pytest.org/en/stable/)

**Lưu ý:** tài liệu thư viện có thể thay đổi. Trước khi đưa lệnh cài đặt hoặc nâng cấp vào dự án, kiểm tra phiên bản hiện hành, tương thích Windows/Python và thử trên môi trường ảo sạch.
