"""Operator interface for parking entry, exit, evidence review, and lookup."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import ParkingStatus, VehicleType
from parking_app.domain.exceptions import DomainError
from parking_app.domain.models import ParkingSession, User, Vehicle
from parking_app.domain.plate import PlateRecognition, normalize_plate
from parking_app.domain.vision import EventCandidate, GateDirection


class ParkingManagementWidget(QWidget):
    """Provide explicit operator confirmation for parking entry and exit."""

    plate_recognition_requested = Signal(str, object)
    session_state_changed = Signal()
    SESSION_HEADERS = ("Mã lượt", "Biển số", "Loại xe", "Giờ vào", "Giờ ra", "Trạng thái")

    def __init__(
        self,
        parking_service: ParkingService,
        current_user: User,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.parking_service = parking_service
        self.current_user = current_user
        self.entry_image_path: str | None = None
        self._entry_candidate_source = None
        self._exit_candidate_source = None
        self._entry_capture_data: bytes | None = None
        self.exit_image_path: str | None = None
        self._exit_capture_data: bytes | None = None
        self._pending_exit_candidate = False
        self._active_plate_candidate_id: str | None = None
        self._active_plate_mode: str | None = None
        self._entry_plate_edited = False
        self._exit_plate_edited = False
        self._entry_plate_recognition: PlateRecognition | None = None
        self._exit_plate_recognition: PlateRecognition | None = None
        self._exit_plate_ocr_status = ""
        self._entry_ai_vehicle_type: VehicleType | None = None
        self._exit_ai_vehicle_type: VehicleType | None = None
        self.selected_session_id: int | None = None
        self._entry_registered_vehicle: Vehicle | None = None
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.capacity_label = QLabel()
        layout.addWidget(self.capacity_label)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_entry_tab(), "Xác nhận xe vào")
        self.tabs.addTab(self._build_exit_tab(), "Xe đang gửi / xác nhận ra")
        self.tabs.addTab(self._build_history_tab(), "Tra cứu lượt")
        layout.addWidget(self.tabs)

    def _build_entry_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form_box = QGroupBox("Thông tin xe vào")
        form = QFormLayout(form_box)

        self.entry_plate_input = QLineEdit()
        self.entry_plate_input.setPlaceholderText("Để trống nếu chưa đọc được biển số")
        form.addRow("Biển số:", self.entry_plate_input)
        self.entry_plate_status = QLabel("OCR chỉ đề xuất; nhân viên cần kiểm tra và xác nhận.")
        self.entry_plate_status.setWordWrap(True)
        form.addRow("Trạng thái OCR:", self.entry_plate_status)

        self.entry_type_combo = QComboBox()
        self.entry_type_combo.addItem("Xe máy", VehicleType.MOTORCYCLE)
        self.entry_type_combo.addItem("Ô tô", VehicleType.CAR)
        form.addRow("Loại phương tiện:", self.entry_type_combo)

        self.entry_type_warning = QLabel()
        self.entry_type_warning.setWordWrap(True)
        self.entry_type_warning.setStyleSheet("color: #b71c1c; font-weight: bold;")
        form.addRow(self.entry_type_warning)
        self.entry_attention_check = QCheckBox("Đánh dấu lượt này cần xử lý thêm")
        self.entry_attention_check.hide()
        form.addRow(self.entry_attention_check)
        self.entry_plate_input.textChanged.connect(self._refresh_entry_vehicle_match)
        self.entry_plate_input.textEdited.connect(self._mark_entry_plate_edited)
        self.entry_type_combo.currentIndexChanged.connect(self._refresh_entry_vehicle_match)

        self.entry_note_input = QLineEdit()
        self.entry_note_input.setPlaceholderText("Ghi chú (không bắt buộc)")
        form.addRow("Ghi chú:", self.entry_note_input)

        image_row = QHBoxLayout()
        self.entry_image_preview = self._new_preview("Chưa chọn ảnh vào")
        image_row.addWidget(self.entry_image_preview, 1)
        choose_image = QPushButton("Chọn ảnh vào…")
        choose_image.clicked.connect(self._choose_entry_image)
        image_row.addWidget(choose_image)
        form.addRow("Ảnh bằng chứng:", image_row)
        layout.addWidget(form_box)

        self.create_entry_button = QPushButton("Xác nhận xe vào")
        self.create_entry_button.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 8px;"
        )
        self.create_entry_button.clicked.connect(self._create_entry)
        layout.addWidget(self.create_entry_button)
        layout.addStretch()
        return page

    def _build_exit_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.active_table = self._new_session_table()
        self.active_table.itemSelectionChanged.connect(self._on_active_selection_changed)
        layout.addWidget(QLabel("Chọn đúng lượt đang mở để kiểm tra trước khi xác nhận xe ra:"))
        layout.addWidget(self.active_table, 1)

        evidence_box = QGroupBox("Đối chiếu bằng chứng trước khi đóng lượt")
        evidence_layout = QHBoxLayout(evidence_box)
        self.exit_entry_preview = self._new_preview("Ảnh lúc vào")
        self.exit_image_preview = self._new_preview("Chưa chọn ảnh ra")
        evidence_layout.addWidget(self._preview_group("Ảnh lúc vào", self.exit_entry_preview), 1)

        exit_controls = QVBoxLayout()
        exit_controls.addWidget(self._preview_group("Ảnh lúc ra", self.exit_image_preview), 1)
        choose_image = QPushButton("Chọn ảnh ra…")
        choose_image.clicked.connect(self._choose_exit_image)
        exit_controls.addWidget(choose_image)
        evidence_layout.addLayout(exit_controls, 1)
        layout.addWidget(evidence_box)

        plate_search = QHBoxLayout()
        self.exit_plate_input = QLineEdit()
        self.exit_plate_input.setPlaceholderText("Biển OCR đề xuất — có thể sửa/nhập tay")
        self.exit_plate_input.textEdited.connect(self._mark_exit_plate_edited)
        self.exit_plate_status = QLabel("OCR chỉ lọc lượt; nhân viên phải chọn đúng lượt.")
        self.exit_plate_status.setWordWrap(True)
        find_plate = QPushButton("Tìm lượt theo biển")
        find_plate.clicked.connect(self._filter_active_sessions_by_plate)
        plate_search.addWidget(self.exit_plate_input, 1)
        plate_search.addWidget(find_plate)
        layout.addLayout(plate_search)
        layout.addWidget(self.exit_plate_status)

        actions = QHBoxLayout()
        self.flag_button = QPushButton("Đánh dấu cần xử lý")
        self.flag_button.clicked.connect(self._flag_selected_session)
        actions.addWidget(self.flag_button)
        if self.current_user.is_admin:
            self.delete_session_button = QPushButton("Xóa lượt đang gửi")
            self.delete_session_button.clicked.connect(self._delete_selected_session)
            actions.addWidget(self.delete_session_button)
        actions.addStretch()
        self.close_exit_button = QPushButton("Xác nhận xe ra")
        self.close_exit_button.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold; padding: 8px;"
        )
        self.close_exit_button.clicked.connect(self._close_exit)
        actions.addWidget(self.close_exit_button)
        layout.addLayout(actions)
        return page

    def _build_history_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        filters = QVBoxLayout()
        lookup_row = QHBoxLayout()
        self.history_query_input = QLineEdit()
        self.history_query_input.setPlaceholderText("Biển số hoặc mã lượt")
        self.history_query_input.returnPressed.connect(self._search_history)
        lookup_row.addWidget(self.history_query_input, 1)
        self.history_customer_input = QLineEdit()
        self.history_customer_input.setPlaceholderText("Mã, tên hoặc điện thoại khách hàng")
        lookup_row.addWidget(self.history_customer_input, 1)
        filters.addLayout(lookup_row)

        filter_row = QHBoxLayout()
        self.history_status_combo = QComboBox()
        self.history_status_combo.addItem("Tất cả trạng thái", None)
        self.history_status_combo.addItem("Đang gửi", ParkingStatus.DANG_GUI)
        self.history_status_combo.addItem("Đã ra", ParkingStatus.DA_RA)
        filter_row.addWidget(self.history_status_combo)

        self.history_type_combo = QComboBox()
        self.history_type_combo.addItem("Tất cả phương tiện", None)
        self.history_type_combo.addItem("Xe máy", VehicleType.MOTORCYCLE)
        self.history_type_combo.addItem("Ô tô", VehicleType.CAR)
        filter_row.addWidget(self.history_type_combo)

        self.history_from_input = QLineEdit()
        self.history_from_input.setPlaceholderText("Từ ngày (YYYY-MM-DD)")
        filter_row.addWidget(self.history_from_input)
        self.history_to_input = QLineEdit()
        self.history_to_input.setPlaceholderText("Đến ngày (YYYY-MM-DD)")
        filter_row.addWidget(self.history_to_input)

        self.attention_only_check = QCheckBox("Chỉ cần xử lý")
        filter_row.addWidget(self.attention_only_check)
        search_button = QPushButton("Tra cứu")
        search_button.clicked.connect(self._search_history)
        filter_row.addWidget(search_button)
        filters.addLayout(filter_row)
        layout.addLayout(filters)

        self.history_table = self._new_session_table()
        self.history_table.itemSelectionChanged.connect(self._on_history_selection_changed)
        layout.addWidget(self.history_table, 1)

        history_evidence = QHBoxLayout()
        self.history_entry_preview = self._new_preview("Ảnh lúc vào")
        self.history_exit_preview = self._new_preview("Ảnh lúc ra")
        history_evidence.addWidget(self._preview_group("Ảnh vào", self.history_entry_preview), 1)
        history_evidence.addWidget(self._preview_group("Ảnh ra", self.history_exit_preview), 1)
        layout.addLayout(history_evidence)

        self.unmatched_exit_button = QPushButton("Ghi nhận không tìm thấy lượt xe ra")
        self.unmatched_exit_button.clicked.connect(self._record_unmatched_exit)
        layout.addWidget(self.unmatched_exit_button)
        return page

    @staticmethod
    def _new_preview(text: str) -> QLabel:
        preview = QLabel(text)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setMinimumSize(250, 140)
        preview.setMaximumHeight(180)
        preview.setStyleSheet("border: 1px solid #9e9e9e; background: #f5f5f5;")
        return preview

    @staticmethod
    def _preview_group(title: str, preview: QLabel) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(preview)
        return group

    @classmethod
    def _new_session_table(cls) -> QTableWidget:
        table = QTableWidget(0, len(cls.SESSION_HEADERS))
        table.setHorizontalHeaderLabels(cls.SESSION_HEADERS)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def refresh(self) -> None:
        try:
            summary = self.parking_service.get_capacity_summary()
            capacity_warning = summary.is_motorcycle_full or summary.is_car_full
            self.capacity_label.setText(
                f"Sức chứa: xe máy {summary.motorcycle_active}/{summary.motorcycle_capacity} "
                f"(còn {summary.motorcycle_remaining})  |  "
                f"ô tô {summary.car_active}/{summary.car_capacity} "
                f"(còn {summary.car_remaining})  |  "
                f"Tổng {summary.total_active}/{summary.total_capacity}"
                f"{' — CẢNH BÁO: có loại xe đã hết chỗ' if capacity_warning else ''}"
            )
            self.capacity_label.setStyleSheet(
                "font-weight: bold; color: #b71c1c;"
                if capacity_warning
                else "font-weight: bold; color: #0d47a1;"
            )
            sessions = self.parking_service.list_active_sessions()
            self._populate_active_table(sessions)
            self._search_history()
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi tải dữ liệu", f"Không thể tải dữ liệu bãi xe:\n{exc}")

    def _populate_active_table(self, sessions: list[ParkingSession]) -> None:
        query = normalize_plate(self.exit_plate_input.text())
        if query:
            sessions = [
                session for session in sessions if query in normalize_plate(session.snapshot_plate)
            ]
        self._populate_table(self.active_table, sessions)
        if query:
            self.exit_plate_status.setText(
                f"{self._exit_plate_ocr_status} "
                f"Tìm thấy {len(sessions)} lượt đang gửi khớp một phần với {query}. "
                "Hãy chọn đúng lượt và đối chiếu ảnh vào/ra."
            )
        elif self._exit_plate_ocr_status:
            self.exit_plate_status.setText(self._exit_plate_ocr_status)

    def _filter_active_sessions_by_plate(self) -> None:
        try:
            sessions = self.parking_service.list_active_sessions()
            self._populate_active_table(sessions)
            if not normalize_plate(self.exit_plate_input.text()):
                self.exit_plate_status.setText(
                    f"{self._exit_plate_ocr_status} "
                    "Nhập hoặc sửa biển số rồi tìm; không có lượt nào được tự chọn."
                )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Lỗi tra cứu lượt",
                f"Không thể lọc lượt đang gửi theo biển số:\n{exc}",
            )

    def _choose_entry_image(self) -> None:
        previous_path = self.entry_image_path
        self.entry_image_path = self._choose_image(
            self.entry_image_preview,
            self.entry_image_path,
        )
        if self.entry_image_path and self.entry_image_path != previous_path:
            self._entry_capture_data = None
            self._entry_candidate_source = None
            self._request_plate_recognition("entry", self._jpeg_bytes(self.entry_image_path))

    def _choose_exit_image(self) -> None:
        previous_path = self.exit_image_path
        self.exit_image_path = self._choose_image(
            self.exit_image_preview,
            self.exit_image_path,
        )
        if self.exit_image_path and self.exit_image_path != previous_path:
            self._exit_capture_data = None
            self._exit_candidate_source = None
            self._request_plate_recognition("exit", self._jpeg_bytes(self.exit_image_path))

    def stage_event_candidate(self, candidate: EventCandidate) -> None:
        """Stage a camera or MP4 detection for review; never confirms a session."""
        if candidate.direction == GateDirection.ENTRY:
            self.tabs.setCurrentIndex(0)
            self.entry_plate_input.clear()
            self._entry_plate_edited = False
            self._entry_plate_recognition = None
            self._entry_ai_vehicle_type = candidate.vehicle_type
            self.entry_plate_status.setText("Đang đề xuất vùng biển và nhận dạng OCR…")
            self.entry_type_combo.setCurrentIndex(
                self.entry_type_combo.findData(candidate.vehicle_type)
            )
            self.entry_image_path = None
            self._entry_candidate_source = candidate.source_kind
            self._entry_capture_data = candidate.image_data
            self._set_preview_data(
                self.entry_image_preview,
                candidate.image_data,
                "Ảnh xe đề xuất — cần nhân viên kiểm tra",
            )
            self.entry_note_input.setText(
                f"Đề xuất qua vạch từ {candidate.source_name}, track #{candidate.track_id}; "
                "OCR chỉ đề xuất, cần nhân viên kiểm tra."
            )
            self.entry_plate_input.setFocus()
            self._active_plate_candidate_id = candidate.id
            self._active_plate_mode = "entry"
            self.plate_recognition_requested.emit(
                candidate.id,
                candidate.vehicle_image_samples or (candidate.image_data,),
            )
            return

        self.tabs.setCurrentIndex(1)
        self.active_table.clearSelection()
        self.selected_session_id = None
        self._pending_exit_candidate = True
        self._exit_plate_edited = False
        self._exit_plate_recognition = None
        self._exit_ai_vehicle_type = candidate.vehicle_type
        self.exit_plate_input.clear()
        self._exit_plate_ocr_status = "Đang đề xuất vùng biển và nhận dạng OCR…"
        self.exit_plate_status.setText(self._exit_plate_ocr_status)
        self.exit_image_path = None
        self._exit_candidate_source = candidate.source_kind
        self._exit_capture_data = candidate.image_data
        self._set_preview_data(
            self.exit_image_preview,
            candidate.image_data,
            "Ảnh xe ra đề xuất — chọn đúng lượt đang mở để đối chiếu",
        )
        self._active_plate_candidate_id = candidate.id
        self._active_plate_mode = "exit"
        self._populate_active_table(self.parking_service.list_active_sessions())
        self.plate_recognition_requested.emit(
            candidate.id,
            candidate.vehicle_image_samples or (candidate.image_data,),
        )

    def stage_plate_recognition(
        self,
        candidate_id: str,
        result: PlateRecognition,
    ) -> None:
        if candidate_id != self._active_plate_candidate_id:
            return
        if self._active_plate_mode == "entry":
            self._entry_plate_recognition = result
            if result.proposed_plate and not self._entry_plate_edited:
                self.entry_plate_input.setText(result.proposed_plate)
            self.entry_plate_status.setText(self._plate_status_text(result))
        elif self._active_plate_mode == "exit":
            self._exit_plate_recognition = result
            if result.proposed_plate and not self._exit_plate_edited:
                self.exit_plate_input.setText(result.proposed_plate)
            self._exit_plate_ocr_status = self._plate_status_text(result)
            self._filter_active_sessions_by_plate()

    def stage_plate_recognition_error(self, candidate_id: str, message: str) -> None:
        if candidate_id != self._active_plate_candidate_id:
            return
        status = f"OCR chưa hoàn tất: {message} Nhân viên có thể nhập biển thủ công."
        if self._active_plate_mode == "entry":
            self.entry_plate_status.setText(status)
        elif self._active_plate_mode == "exit":
            self._exit_plate_ocr_status = status
            self.exit_plate_status.setText(status)

    def stage_plate_recognition_pending(self, candidate_id: str) -> None:
        if candidate_id != self._active_plate_candidate_id:
            return
        status = "Đang chờ OCR xử lý đề xuất trước; nhân viên vẫn có thể nhập biển thủ công."
        if self._active_plate_mode == "entry":
            self.entry_plate_status.setText(status)
        elif self._active_plate_mode == "exit":
            self._exit_plate_ocr_status = status
            self.exit_plate_status.setText(status)

    def _request_plate_recognition(self, mode: str, image_data: bytes) -> None:
        candidate_id = uuid.uuid4().hex
        self._active_plate_candidate_id = candidate_id
        self._active_plate_mode = mode
        if mode == "entry":
            self._entry_plate_edited = bool(self.entry_plate_input.text().strip())
            self._entry_plate_recognition = None
            self._entry_ai_vehicle_type = None
            self.entry_plate_status.setText("Đang đề xuất vùng biển và nhận dạng OCR…")
        else:
            self._exit_plate_edited = bool(self.exit_plate_input.text().strip())
            self._exit_plate_recognition = None
            self._exit_ai_vehicle_type = None
            self._exit_plate_ocr_status = "Đang đề xuất vùng biển và nhận dạng OCR…"
            self.exit_plate_status.setText(self._exit_plate_ocr_status)
        self.plate_recognition_requested.emit(candidate_id, (image_data,))

    @staticmethod
    def _plate_status_text(result: PlateRecognition) -> str:
        if result.proposed_plate is None:
            raw_text = result.raw_text or "không tìm thấy chuỗi biển hợp lệ"
            return (
                f"OCR thô: {raw_text}; không có đề xuất chắc chắn. "
                "Nhân viên kiểm tra ảnh và có thể nhập tay."
            )
        confidence = result.confidence or 0
        certainty = "thấp — cần kiểm tra kỹ" if confidence < 0.8 else "đề xuất để đối chiếu"
        return (
            f"OCR đề xuất {result.proposed_plate} ({confidence:.0%}, {certainty}); "
            f"đã so sánh {result.samples_considered} ảnh."
        )

    @staticmethod
    def _set_preview_data(preview: QLabel, image_data: bytes, description: str) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_data, "JPEG"):
            preview.setPixmap(QPixmap())
            preview.setText("Không đọc được ảnh đề xuất.")
            raise ValueError("Ảnh sự kiện không hợp lệ.")
        preview.setText(description)
        preview.setPixmap(
            pixmap.scaled(
                preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _choose_image(self, preview: QLabel, current_path: str | None) -> str | None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh bằng chứng",
            "",
            "Tệp ảnh (*.jpg *.jpeg *.png *.bmp)",
        )
        if not file_path:
            return current_path
        image = QImage(file_path)
        if image.isNull():
            QMessageBox.warning(self, "Ảnh không hợp lệ", "Không thể đọc tệp ảnh đã chọn.")
            return current_path
        self._set_preview(preview, file_path)
        return file_path

    def _refresh_entry_vehicle_match(self) -> None:
        plate = self.entry_plate_input.text().strip()
        if not plate:
            self._entry_registered_vehicle = None
        else:
            try:
                self._entry_registered_vehicle = self.parking_service.find_registered_vehicle(plate)
            except Exception as exc:
                self._entry_registered_vehicle = None
                QMessageBox.critical(
                    self,
                    "Lỗi tra cứu phương tiện",
                    f"Không thể kiểm tra hồ sơ biển số:\n{exc}",
                )
                return

        vehicle = self._entry_registered_vehicle
        selected_type = VehicleType(self.entry_type_combo.currentData())
        is_mismatch = vehicle is not None and vehicle.vehicle_type != selected_type
        if is_mismatch:
            self.entry_type_warning.setText(
                f"Cảnh báo loại xe: hồ sơ đăng ký là {vehicle.vehicle_type.display_name}, "
                f"nhưng loại đang xác nhận là {selected_type.display_name}."
            )
            self.entry_attention_check.show()
        elif vehicle is not None:
            self.entry_type_warning.setText(
                f"Đã tìm thấy xe trong hồ sơ: loại đăng ký {vehicle.vehicle_type.display_name}."
            )
            self.entry_attention_check.hide()
            self.entry_attention_check.setChecked(False)
        else:
            self.entry_type_warning.clear()
            self.entry_attention_check.hide()
            self.entry_attention_check.setChecked(False)

    def _mark_entry_plate_edited(self) -> None:
        self._entry_plate_edited = True

    def _mark_exit_plate_edited(self) -> None:
        self._exit_plate_edited = True

    def _create_entry(self) -> None:
        if not self.entry_image_path and not self._entry_capture_data:
            QMessageBox.warning(self, "Thiếu bằng chứng", "Cần chọn ảnh lúc xe vào.")
            return
        vehicle_type = VehicleType(self.entry_type_combo.currentData())
        registered_vehicle = self._entry_registered_vehicle
        type_mismatch = (
            registered_vehicle is not None and registered_vehicle.vehicle_type != vehicle_type
        )
        if type_mismatch:
            answer = QMessageBox.question(
                self,
                "Loại xe không khớp hồ sơ",
                f"Hồ sơ ghi {registered_vehicle.vehicle_type.display_name}, "
                f"nhưng nhân viên xác nhận {vehicle_type.display_name}. "
                "Bạn đã kiểm tra ảnh và muốn tiếp tục?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            summary = self.parking_service.get_capacity_summary()
            type_is_full = (
                summary.is_motorcycle_full
                if vehicle_type == VehicleType.MOTORCYCLE
                else summary.is_car_full
            )
            if type_is_full:
                answer = QMessageBox.question(
                    self,
                    "Cảnh báo sức chứa",
                    f"Khu vực {vehicle_type.display_name.lower()} đã đạt sức chứa cấu hình. "
                    "Hệ thống vẫn ghi nhận lượt nhưng cần hướng dẫn khách sang khu vực khác. "
                    "Bạn muốn tiếp tục?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
            attention_reason = None
            if type_mismatch and self.entry_attention_check.isChecked():
                attention_reason = (
                    f"Loại xe đã đăng ký là {registered_vehicle.vehicle_type.display_name}; "
                    f"nhân viên xác nhận {vehicle_type.display_name}."
                )
            image_data = (
                self._entry_capture_data
                if self._entry_capture_data is not None
                else self._jpeg_bytes(self.entry_image_path)
            )
            session = self.parking_service.create_entry(
                actor=self.current_user,
                source_kind=self._entry_candidate_source,
                raw_plate=self.entry_plate_input.text(),
                vehicle_type=vehicle_type,
                image_data=image_data,
                note=self.entry_note_input.text(),
                attention_reason=attention_reason,
                ocr_raw_text=(
                    self._entry_plate_recognition.raw_text
                    if self._entry_plate_recognition
                    else None
                ),
                ocr_proposed_plate=(
                    self._entry_plate_recognition.proposed_plate
                    if self._entry_plate_recognition
                    else None
                ),
                ocr_confidence=(
                    self._entry_plate_recognition.confidence
                    if self._entry_plate_recognition
                    else None
                ),
                plate_image_data=(
                    self._entry_plate_recognition.plate_image_data
                    if self._entry_plate_recognition
                    else None
                ),
                proposed_vehicle_type=self._entry_ai_vehicle_type,
            )
            self.entry_plate_input.clear()
            self.entry_note_input.clear()
            self.entry_image_path = None
            self._entry_capture_data = None
            self._entry_candidate_source = None
            self.entry_image_preview.setPixmap(QPixmap())
            self.entry_image_preview.setText("Chưa chọn ảnh vào")
            self.entry_attention_check.setChecked(False)
            self._entry_plate_recognition = None
            self._entry_ai_vehicle_type = None
            self._entry_plate_edited = False
            self._active_plate_candidate_id = None
            self._active_plate_mode = None
            self.entry_plate_status.setText("OCR chỉ đề xuất; nhân viên cần kiểm tra và xác nhận.")
            self.entry_type_warning.clear()
            self._entry_registered_vehicle = None
            self.refresh()
            self.session_state_changed.emit()
            QMessageBox.information(
                self,
                "Xe vào đã xác nhận",
                f"Đã tạo lượt {session.session_code} cho biển số {session.snapshot_display_plate}.",
            )
        except DomainError as exc:
            QMessageBox.warning(self, "Không thể xác nhận xe vào", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xác nhận xe vào", f"Không thể lưu lượt xe:\n{exc}")

    def _on_active_selection_changed(self) -> None:
        selected_row = self.active_table.currentRow()
        if selected_row < 0:
            self.selected_session_id = None
            self.exit_entry_preview.setPixmap(QPixmap())
            self.exit_entry_preview.setText("Ảnh lúc vào")
            return
        selected_item = self.active_table.item(selected_row, 0)
        if selected_item is None:
            return
        session_id = selected_item.data(Qt.ItemDataRole.UserRole)
        session = self.parking_service.get_session(session_id)
        if session is None:
            self.selected_session_id = None
            QMessageBox.warning(
                self, "Không tìm thấy lượt", "Lượt đã thay đổi hoặc không còn tồn tại."
            )
            self.refresh()
            return
        self.selected_session_id = session.id
        if self._pending_exit_candidate:
            self._pending_exit_candidate = False
        else:
            self.exit_image_path = None
            self._exit_capture_data = None
            self._exit_candidate_source = None
            self.exit_image_preview.setPixmap(QPixmap())
            self.exit_image_preview.setText("Chưa chọn ảnh ra")
        if session.entry_image_path:
            self._set_preview(self.exit_entry_preview, session.entry_image_path)
        else:
            self.exit_entry_preview.setPixmap(QPixmap())
            self.exit_entry_preview.setText("Lượt này không có ảnh vào")
        warnings = []
        if (
            self._exit_plate_recognition
            and self._exit_plate_recognition.proposed_plate
            and normalize_plate(self._exit_plate_recognition.proposed_plate)
            != normalize_plate(session.snapshot_plate)
        ):
            warnings.append(
                f"OCR đề xuất {self._exit_plate_recognition.proposed_plate}, "
                f"nhưng lượt là {session.snapshot_display_plate}"
            )
        if (
            self._exit_ai_vehicle_type is not None
            and self._exit_ai_vehicle_type != session.snapshot_vehicle_type
        ):
            warnings.append(
                f"AI nhận dạng {self._exit_ai_vehicle_type.display_name}, "
                f"nhưng lượt đã đăng ký là {session.snapshot_vehicle_type.display_name}"
            )
        if warnings:
            self.exit_plate_status.setText(
                f"{self._exit_plate_ocr_status} Cảnh báo: "
                + "; ".join(warnings)
                + ". Chỉ tiếp tục nếu nhân viên đã đối chiếu ảnh."
            )

    def _delete_selected_session(self) -> None:
        if self.selected_session_id is None:
            QMessageBox.warning(self, "Chưa chọn lượt", "Hãy chọn một lượt đang gửi.")
            return
        target = self.parking_service.get_session(self.selected_session_id)
        if target is None:
            QMessageBox.warning(self, "Không tìm thấy lượt", "Lượt không còn tồn tại.")
            self.refresh()
            return
        answer = QMessageBox.question(
            self, "Xóa lượt đang gửi",
            f"Xóa lượt {target.session_code} của xe {target.snapshot_display_plate}? "
            "Thao tác này không thể hoàn tác.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.parking_service.delete_active_session(self.current_user, target.id)
            self.selected_session_id = None
            self.refresh()
            self.session_state_changed.emit()
            QMessageBox.information(self, "Đã xóa lượt", f"Đã xóa lượt {target.session_code}.")
        except DomainError as exc:
            QMessageBox.warning(self, "Không thể xóa lượt", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xóa lượt", f"Không thể xóa lượt xe:\n{exc}")

    def _close_exit(self) -> None:
        if self.selected_session_id is None:
            QMessageBox.warning(self, "Chưa chọn lượt", "Hãy chọn một lượt đang gửi.")
            return
        if not self.exit_image_path and not self._exit_capture_data:
            QMessageBox.warning(self, "Thiếu bằng chứng", "Cần chọn ảnh lúc xe ra để đối chiếu.")
            return
        session = self.parking_service.get_session(self.selected_session_id)
        if session is None:
            QMessageBox.warning(self, "Không tìm thấy lượt", "Lượt không còn tồn tại.")
            self.refresh()
            return
        answer = QMessageBox.question(
            self,
            "Xác nhận xe ra",
            f"Đã đối chiếu ảnh vào/ra và xác nhận xe {session.snapshot_display_plate}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            closed = self.parking_service.close_exit(
                actor=self.current_user,
                source_kind=self._exit_candidate_source,
                session_id_or_code=self.selected_session_id,
                image_data=(
                    self._exit_capture_data
                    if self._exit_capture_data is not None
                    else self._jpeg_bytes(self.exit_image_path)
                ),
                ocr_raw_text=(
                    self._exit_plate_recognition.raw_text if self._exit_plate_recognition else None
                ),
                ocr_proposed_plate=(
                    self._exit_plate_recognition.proposed_plate
                    if self._exit_plate_recognition
                    else None
                ),
                ocr_confidence=(
                    self._exit_plate_recognition.confidence
                    if self._exit_plate_recognition
                    else None
                ),
                plate_image_data=(
                    self._exit_plate_recognition.plate_image_data
                    if self._exit_plate_recognition
                    else None
                ),
                proposed_vehicle_type=self._exit_ai_vehicle_type,
            )
            self.selected_session_id = None
            self.exit_image_path = None
            self._exit_capture_data = None
            self._exit_candidate_source = None
            self._exit_plate_recognition = None
            self._exit_ai_vehicle_type = None
            self._exit_plate_edited = False
            self._active_plate_candidate_id = None
            self._active_plate_mode = None
            self.exit_plate_input.clear()
            self._exit_plate_ocr_status = ""
            self.exit_plate_status.setText("OCR chỉ lọc lượt; nhân viên phải chọn đúng lượt.")
            self.refresh()
            self.session_state_changed.emit()
            QMessageBox.information(
                self,
                "Xe ra đã xác nhận",
                f"Đã đóng lượt {closed.session_code}.",
            )
        except DomainError as exc:
            QMessageBox.warning(self, "Không thể xác nhận xe ra", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi xác nhận xe ra", f"Không thể đóng lượt xe:\n{exc}")

    def _flag_selected_session(self) -> None:
        if self.selected_session_id is None:
            QMessageBox.warning(self, "Chưa chọn lượt", "Hãy chọn một lượt đang gửi.")
            return
        reason, accepted = QInputDialog.getText(
            self,
            "Đánh dấu cần xử lý",
            "Lý do cần kiểm tra:",
        )
        if not accepted:
            return
        try:
            self.parking_service.flag_session_attention(
                self.current_user,
                self.selected_session_id,
                reason,
            )
            self.refresh()
            self.session_state_changed.emit()
        except DomainError as exc:
            QMessageBox.warning(self, "Không thể đánh dấu", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi", f"Không thể cập nhật lượt:\n{exc}")

    def _search_history(self) -> None:
        if not hasattr(self, "history_table"):
            return
        try:
            status_value = self.history_status_combo.currentData()
            vehicle_type_value = self.history_type_combo.currentData()
            entry_from, entry_before = self._history_date_bounds()
            sessions = self.parking_service.search_sessions(
                plate_query=self.history_query_input.text(),
                customer_query=self.history_customer_input.text(),
                status=ParkingStatus(status_value) if status_value else None,
                vehicle_type=VehicleType(vehicle_type_value) if vehicle_type_value else None,
                needs_attention_only=self.attention_only_check.isChecked(),
                entry_from=entry_from,
                entry_before=entry_before,
            )
            self._populate_table(self.history_table, sessions)
            self.history_entry_preview.setPixmap(QPixmap())
            self.history_entry_preview.setText("Ảnh lúc vào")
            self.history_exit_preview.setPixmap(QPixmap())
            self.history_exit_preview.setText("Ảnh lúc ra")
        except ValueError as exc:
            QMessageBox.warning(self, "Khoảng thời gian không hợp lệ", str(exc))
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi tra cứu", f"Không thể tra cứu lượt xe:\n{exc}")

    def _history_date_bounds(self) -> tuple[datetime | None, datetime | None]:
        from_text = self.history_from_input.text().strip()
        to_text = self.history_to_input.text().strip()
        try:
            start = date.fromisoformat(from_text) if from_text else None
            end = date.fromisoformat(to_text) if to_text else None
        except ValueError as exc:
            raise ValueError("Ngày phải đúng định dạng YYYY-MM-DD.") from exc
        if start is not None and end is not None and start > end:
            raise ValueError("Ngày bắt đầu không được sau ngày kết thúc.")
        entry_from = (
            datetime.combine(start, time.min).astimezone(UTC) if start is not None else None
        )
        entry_before = (
            datetime.combine(end + timedelta(days=1), time.min).astimezone(UTC)
            if end is not None
            else None
        )
        return entry_from, entry_before

    def _on_history_selection_changed(self) -> None:
        row = self.history_table.currentRow()
        item = self.history_table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        session = self.parking_service.get_session(session_id)
        if session is None:
            QMessageBox.warning(self, "Không tìm thấy lượt", "Lượt không còn tồn tại.")
            self._search_history()
            return
        if session.entry_image_path:
            self._set_preview(self.history_entry_preview, session.entry_image_path)
        else:
            self.history_entry_preview.setPixmap(QPixmap())
            self.history_entry_preview.setText("Lượt này không có ảnh vào")
        if session.exit_image_path:
            self._set_preview(self.history_exit_preview, session.exit_image_path)
        else:
            self.history_exit_preview.setPixmap(QPixmap())
            self.history_exit_preview.setText("Lượt này không có ảnh ra")

    def _record_unmatched_exit(self) -> None:
        if self.history_table.rowCount() != 0:
            QMessageBox.warning(
                self,
                "Vẫn có kết quả tra cứu",
                "Chỉ ghi nhận trường hợp không tìm thấy khi danh sách kết quả đang trống.",
            )
            return
        if not any(
            (
                self.history_query_input.text().strip(),
                self.history_customer_input.text().strip(),
                self.history_from_input.text().strip(),
                self.history_to_input.text().strip(),
                self.history_status_combo.currentData(),
                self.history_type_combo.currentData(),
            )
        ):
            QMessageBox.warning(
                self,
                "Chưa tra cứu lượt",
                "Nhập ít nhất một tiêu chí và tra cứu trước khi ghi nhận ngoại lệ.",
            )
            return
        reason, accepted = QInputDialog.getText(
            self,
            "Ghi nhận xe ra chưa tìm thấy lượt",
            "Mô tả thông tin đã đối chiếu và lý do chưa xác định được lượt:",
        )
        if not accepted:
            return
        try:
            entry_from, entry_before = self._history_date_bounds()
            image_data = self._exit_capture_data
            if image_data is None and self.exit_image_path:
                image_data = self._jpeg_bytes(self.exit_image_path)
            vehicle_value = self.history_type_combo.currentData()
            incident_code = self.parking_service.record_unmatched_exit(
                actor=self.current_user,
                reason=reason,
                plate_query=self.history_query_input.text(),
                customer_query=self.history_customer_input.text(),
                vehicle_type=VehicleType(vehicle_value) if vehicle_value else None,
                entry_from=entry_from,
                entry_before=entry_before,
                image_data=image_data,
            )
            QMessageBox.information(
                self,
                "Đã ghi nhận trường hợp cần xử lý",
                f"Mã ngoại lệ: {incident_code}",
            )
        except DomainError as exc:
            QMessageBox.warning(self, "Không thể ghi nhận", str(exc))
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Lỗi ghi nhận ngoại lệ",
                f"Không thể lưu ngoại lệ:\n{exc}",
            )

    def _populate_table(
        self,
        table: QTableWidget,
        sessions: list[ParkingSession],
    ) -> None:
        table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            values = (
                session.session_code,
                session.snapshot_display_plate,
                session.snapshot_vehicle_type.display_name,
                session.entry_time.strftime("%H:%M:%S %d/%m/%Y"),
                session.exit_time.strftime("%H:%M:%S %d/%m/%Y") if session.exit_time else "",
                self._status_text(session),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, session.id)
                table.setItem(row, column, item)
        table.resizeColumnsToContents()

    @staticmethod
    def _status_text(session: ParkingSession) -> str:
        status = session.status.display_name
        if session.needs_attention:
            return f"{status} — CẦN XỬ LÝ"
        return status

    @staticmethod
    def _jpeg_bytes(file_path: str) -> bytes:
        image = QImage(file_path)
        if image.isNull():
            raise ValueError(f"Không thể đọc ảnh bằng chứng: {file_path}")
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "JPEG", 90):
            raise ValueError(f"Không thể chuyển ảnh bằng chứng sang JPEG: {file_path}")
        return bytes(buffer.data())

    @staticmethod
    def _set_preview(preview: QLabel, file_path: str) -> None:
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            preview.setPixmap(QPixmap())
            preview.setText(f"Không đọc được ảnh:\n{Path(file_path).name}")
            return
        preview.setText("")
        preview.setPixmap(
            pixmap.scaled(
                preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
