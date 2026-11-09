"""G3 source preview, playback, and fixed-purpose camera configuration."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.source_service import SourceService
from parking_app.config.settings import DEFAULT_PLATE_MODEL_PATH
from parking_app.domain.exceptions import DomainError
from parking_app.domain.models import User
from parking_app.domain.video import (
    ParkingSpace,
    ParkingSpaceStatus,
    SourceConfig,
    SourceKind,
    SourcePurpose,
    StreamStatus,
    VideoOptions,
    VisionOptions,
)
from parking_app.domain.vision import EventCandidate
from parking_app.infrastructure.vision.plate_detector import PlateTracker, YOLOPlateDetector
from parking_app.ui.video_canvas import VideoCanvas, bgr_to_qimage
from parking_app.ui.video_worker import VideoWorker


class SourceManagementWidget(QWidget):
    stopped = Signal()
    simulation_changed = Signal(bool)
    review_candidate_requested = Signal(object)
    playback_started = Signal()

    def __init__(
        self,
        service: SourceService,
        actor: User,
        options: VideoOptions | None = None,
        parent=None,
        open_session_count_provider: Callable[[], int] | None = None,
        plate_vision_options: VisionOptions | None = None,
        plate_detector_factory: Callable[[VisionOptions], PlateTracker] = YOLOPlateDetector,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.actor = actor
        self.options = options or VideoOptions()
        self.plate_vision_options = plate_vision_options or VisionOptions(
            model_path=DEFAULT_PLATE_MODEL_PATH
        )
        self.plate_detector_factory = plate_detector_factory
        self.open_session_count_provider = open_session_count_provider
        self._open_session_count: int | None = None
        self._last_open_count_refresh = 0.0
        self._open_count_error: str | None = None
        self.worker: VideoWorker | None = None
        self._pending = None
        self._stopping = False
        self._close_requested = False
        self._selected: SourceConfig | None = None
        self._active: SourceConfig | None = None
        self._parking_spaces: list[ParkingSpace] = []
        self._active_polygon_code: str | None = None
        self._paused = False
        self._last_frame_at = 0.0
        self._status = StreamStatus.STOPPED
        self._build_ui()
        self.refresh_sources()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._check_health)
        self.timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.mode_label = QLabel(
            "Model best.pt phát hiện và theo dõi biển số. PaddleOCR chỉ đọc crop biển số; "
            "nhân viên xác nhận."
        )
        self.mode_label.setWordWrap(True)
        layout.addWidget(self.mode_label)
        row = QHBoxLayout()
        self.sources = QComboBox()
        self.sources.setMinimumWidth(230)
        self.sources.currentIndexChanged.connect(self._select_source)
        row.addWidget(self.sources, 1)
        self.create_source_button = QPushButton("Tạo nguồn mới")
        self.create_source_button.setObjectName("primaryButton")
        self.create_source_button.clicked.connect(self._create_new_source)
        self.create_source_button.setVisible(self.actor.is_admin)
        row.addWidget(self.create_source_button)
        self.open_file_button = QPushButton("Mở MP4 thử nghiệm…")
        self.open_file_button.clicked.connect(self._choose_mp4)
        row.addWidget(self.open_file_button)
        refresh = QPushButton("Tải lại danh sách")
        refresh.clicked.connect(self.refresh_sources)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.source_feedback_label = QLabel()
        self.source_feedback_label.setWordWrap(True)
        layout.addWidget(self.source_feedback_label)

        content = QSplitter(Qt.Orientation.Horizontal)
        content.setChildrenCollapsible(False)
        self.canvas = VideoCanvas()
        self.editor = QGroupBox("Cấu hình nguồn — quản trị viên")
        self.editor.setMinimumWidth(340)
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(10, 12, 10, 10)
        editor_layout.setSpacing(8)
        form_content = QWidget()
        form = QFormLayout(form_content)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(7)
        self.name_input = QLineEdit()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Camera trực tiếp", SourceKind.LIVE)
        self.kind_combo.addItem("MP4 thử nghiệm", SourceKind.MP4)
        self.endpoint_input = QLineEdit()
        self.endpoint_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.endpoint_input.setPlaceholderText("Webcam, URL Camera hoặc đường dẫn MP4")
        self.endpoint_input.setToolTip(
            "Nhập URL luồng của từng camera (RTSP/RTSPS/HTTP/HTTPS), "
            "chỉ số webcam hoặc đường dẫn MP4."
        )
        self.purpose_combo = QComboBox()
        for label, value in (
            ("Cổng vào", SourcePurpose.ENTRY),
            ("Cổng ra", SourcePurpose.EXIT),
            ("Khu đỗ", SourcePurpose.PARKING),
        ):
            self.purpose_combo.addItem(label, value)
        form.addRow("Tên nguồn", self.name_input)
        form.addRow("Loại nguồn", self.kind_combo)
        form.addRow("Nguồn (được che)", self.endpoint_input)
        form.addRow("Mục đích", self.purpose_combo)
        self.canvas.polygon_changed.connect(self._polygon_finished)
        hint = QLabel(
            "Mỗi camera cổng cố định một mục đích VÀO hoặc RA; "
            "hướng đề xuất lấy từ mục đích đã lưu.\n"
            "Với nguồn KHU ĐỖ: nhập mã ô, bắt đầu vẽ, bấm các đỉnh polygon rồi lưu polygon."
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self.space_code_input = QLineEdit()
        self.space_code_input.setPlaceholderText("Ví dụ: A01")
        form.addRow("Mã ô đỗ", self.space_code_input)
        space_controls = QHBoxLayout()
        self.begin_polygon_button = QPushButton("Bắt đầu vẽ polygon")
        self.begin_polygon_button.clicked.connect(self._begin_polygon)
        self.finish_polygon_button = QPushButton("Lưu polygon")
        self.finish_polygon_button.setEnabled(False)
        self.finish_polygon_button.clicked.connect(self.canvas.finish_polygon)
        space_controls.addWidget(self.begin_polygon_button)
        space_controls.addWidget(self.finish_polygon_button)
        form.addRow(space_controls)
        self.space_selector = QComboBox()
        self.space_selector.currentIndexChanged.connect(self._select_space)
        form.addRow("Ô đã cấu hình", self.space_selector)
        self.remove_space_button = QPushButton("Xóa ô đang chọn")
        self.remove_space_button.clicked.connect(self._remove_space)
        form.addRow(self.remove_space_button)

        self.editor_scroll_area = QScrollArea()
        self.editor_scroll_area.setObjectName("sourceEditorScrollArea")
        self.editor_scroll_area.setWidgetResizable(True)
        self.editor_scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_scroll_area.setWidget(form_content)
        editor_layout.addWidget(self.editor_scroll_area, 1)

        action_row = QHBoxLayout()
        self.save_button = QPushButton("Lưu cấu hình nguồn")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._save_source)
        action_row.addWidget(self.save_button, 2)
        self.delete_source_button = QPushButton("Xóa nguồn")
        self.delete_source_button.setObjectName("dangerButton")
        self.delete_source_button.clicked.connect(self._delete_source)
        action_row.addWidget(self.delete_source_button, 1)
        editor_layout.addLayout(action_row)
        self.editor.setVisible(self.actor.is_admin)
        self.editor_scroll_area.setMinimumWidth(0)
        content.addWidget(self.canvas)
        content.addWidget(self.editor)
        content.setStretchFactor(0, 3)
        content.setStretchFactor(1, 2)
        content.setSizes([720, 380])
        layout.addWidget(content, 1)
        self.delete_source_button.setEnabled(False)

        controls = QHBoxLayout()
        self.play_button = QPushButton("Phát / Kết nối / Xem thử")
        self.play_button.clicked.connect(self._play_selected)
        self.pause_button = QPushButton("Tạm dừng")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.stop_button = QPushButton("Dừng")
        self.stop_button.clicked.connect(self.stop_playback)
        self.realtime_check = QCheckBox("Phát theo thời gian video")
        self.realtime_check.setChecked(True)
        self.realtime_check.setToolTip("Bỏ chọn để đọc đủ khung nhanh nhất; MP4 không bỏ khung.")
        for widget in (self.play_button, self.pause_button, self.stop_button, self.realtime_check):
            controls.addWidget(widget)
        layout.addLayout(controls)
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.sliderReleased.connect(self._seek)
        layout.addWidget(self.seek_slider)
        self.position_label = QLabel("Chưa có khung hình")
        self.status_label = QLabel(StreamStatus.STOPPED.value)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.position_label)
        self.parking_summary_label = QLabel("Trạng thái ô đỗ: chọn camera khu đỗ.")
        self.parking_summary_label.setWordWrap(True)
        layout.addWidget(self.parking_summary_label)
        layout.addWidget(self.status_label)
        layout.addWidget(
            QLabel("Xe phát hiện — hướng theo mục đích camera, cần nhân viên xác nhận:")
        )
        candidate_row = QHBoxLayout()
        self.candidate_list = QListWidget()
        self.candidate_list.setMaximumHeight(72)
        self.candidate_list.currentRowChanged.connect(self._update_candidate_controls)
        candidate_row.addWidget(self.candidate_list, 3)
        self.review_candidate_button = QPushButton("Chuyển đề xuất sang bước xác nhận")
        self.review_candidate_button.clicked.connect(self._review_selected_candidate)
        candidate_row.addWidget(self.review_candidate_button, 1)
        layout.addLayout(candidate_row)
        self._update_controls()
        self._update_candidate_controls()

    def refresh_sources(self, selected_id: str | None = None) -> None:
        try:
            configs = self.service.list_sources(self.actor)
        except DomainError as exc:
            self.status_label.setText(str(exc))
            return
        self.stop_playback()
        self.sources.blockSignals(True)
        self.sources.clear()
        self.sources.addItem("— Chọn nguồn đã lưu —", None)
        for config in configs:
            self.sources.addItem(config.name, config)
        index = next((i + 1 for i, c in enumerate(configs) if c.id == selected_id), 0)
        self.sources.setCurrentIndex(index)
        self.sources.blockSignals(False)
        self._select_source()

    def _select_source(self, *_args) -> None:
        self.stop_playback()
        config = self.sources.currentData()
        self._load_config(config)
        if config is None:
            if self.actor.is_admin:
                self.source_feedback_label.setText(
                    "Đang tạo nguồn mới. Nhập thông tin bên phải, xem thử nếu cần, "
                    "rồi nhấn “Lưu cấu hình nguồn”."
                )
            else:
                self.source_feedback_label.setText("Chọn một nguồn đã lưu để xem hình.")
        else:
            self.source_feedback_label.setText(f"Đang chỉnh sửa nguồn: {config.name}.")

    def _create_new_source(self) -> None:
        if not self.actor.is_admin:
            return
        self.stop_playback()
        self.sources.blockSignals(True)
        self.sources.setCurrentIndex(0)
        self.sources.blockSignals(False)
        self._load_config(None)
        self.source_feedback_label.setText(
            "Tạo nguồn mới: nhập tên, loại, địa chỉ và mục đích nguồn; "
            "sau đó nhấn “Lưu cấu hình nguồn”."
        )
        self.name_input.setFocus()

    def _load_config(self, config: SourceConfig | None) -> None:
        self._active = None
        self._selected = config
        selected_source = self.sources.currentData()
        self.delete_source_button.setEnabled(
            self.actor.is_admin
            and config is not None
            and isinstance(selected_source, SourceConfig)
            and selected_source.id == config.id
        )
        self.name_input.setText(config.name if config else "")
        self.endpoint_input.setText(config.endpoint if config and self.actor.is_admin else "")
        self.kind_combo.setCurrentIndex(1 if config and config.kind == SourceKind.MP4 else 0)
        self.purpose_combo.setCurrentIndex(
            self.purpose_combo.findData(config.purpose) if config else 0
        )
        self._parking_spaces = list(config.parking_spaces) if config else []
        self.canvas.set_parking_spaces(tuple(self._parking_spaces))
        self._refresh_space_selector()
        self._render_parking_summary()
        self.canvas.update()
        self._update_controls()

    def _draft(self) -> SourceConfig:
        if not self.actor.is_admin:
            if self._selected is None:
                raise ValueError("Hãy chọn nguồn hoặc mở một tệp MP4.")
            return self._selected
        config = SourceConfig(
            id=self._selected.id if self._selected else uuid.uuid4().hex,
            name=self.name_input.text().strip(),
            kind=SourceKind(self.kind_combo.currentData()),
            endpoint=self.endpoint_input.text().strip(),
            purpose=SourcePurpose(self.purpose_combo.currentData()),
            parking_spaces=tuple(self._parking_spaces),
        )
        config.validate()
        return config

    def _play_selected(self) -> None:
        try:
            self.start_playback(self._draft())
        except (DomainError, ValueError) as exc:
            QMessageBox.warning(self, "Nguồn hình", str(exc))

    def _choose_mp4(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Video thử nghiệm", "", "MP4 (*.mp4)")
        if not path:
            return
        config = SourceConfig(uuid.uuid4().hex, Path(path).stem, SourceKind.MP4, path)
        self.stop_playback()
        self.sources.blockSignals(True)
        self.sources.setCurrentIndex(0)
        self.sources.blockSignals(False)
        self._load_config(config)
        self._play_selected()

    def start_playback(self, config: SourceConfig, initial_index: int = 0) -> None:
        self.service.authorize(self.actor)
        config.validate()
        self._pending = (config, self.realtime_check.isChecked(), initial_index)
        if self.worker is not None:
            self._stopping = True
            self.worker.stop()
            self._clear_image("Đang dừng nguồn cũ…")
        else:
            self._start_pending()

    def _start_pending(self) -> None:
        if self._pending is None:
            return
        config, realtime, initial_index = self._pending
        self._pending = None
        self._active = config
        self._stopping = self._paused = False
        self._last_frame_at = 0
        self._status = StreamStatus.CONNECTING
        self.seek_slider.setRange(0, 0)
        self._parking_spaces = list(config.parking_spaces)
        self.canvas.set_parking_spaces(tuple(self._parking_spaces))
        self._refresh_space_selector()
        self._render_parking_summary()
        self._clear_image("Đang kết nối…")
        is_file = config.kind == SourceKind.MP4
        self.mode_label.setText(
            "MP4 — THỬ NGHIỆM: chọn biển số phát hiện để kiểm tra và xác nhận."
            if is_file
            else (
                "KHU ĐỖ — trạng thái ô được ước lượng từ vùng biển số nhìn thấy."
                if config.purpose == SourcePurpose.PARKING
                else (
                    "CỔNG VÀO — biển số mới chuyển sang OCR để nhân viên xác nhận."
                    if config.purpose == SourcePurpose.ENTRY
                    else "CỔNG RA — biển số mới chuyển sang OCR để nhân viên xác nhận."
                )
            )
        )
        self.simulation_changed.emit(is_file)
        self.candidate_list.clear()
        worker = VideoWorker(
            config,
            self.options,
            realtime=realtime,
            initial_index=initial_index,
            plate_vision_options=self.plate_vision_options,
            plate_detector_factory=self.plate_detector_factory,
        )
        self.worker = worker
        worker.frame_available.connect(self._receive_frame)
        worker.status_changed.connect(self._receive_status)
        worker.stream_reset.connect(self._stream_reset)
        worker.metadata_ready.connect(self._metadata)
        worker.event_candidate.connect(self._receive_candidate)
        worker.finished.connect(self._finished)
        self._update_controls()
        self.playback_started.emit()
        worker.start()

    def stop_playback(self) -> None:
        self._pending = None
        self._clear_image("Đã dừng nguồn hình")
        self._render_parking_summary()
        if self.worker is not None:
            self._stopping = True
            self.status_label.setText("Đang dừng nguồn hình…")
            self.worker.stop()
        else:
            self._status = StreamStatus.STOPPED
            self.status_label.setText(self._status.value)
            self.simulation_changed.emit(False)
        self._update_controls()

    def _finished(self) -> None:
        if self.sender() is not self.worker:
            return
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self._stopping = False
        if self._pending is not None:
            self._start_pending()
        else:
            self.simulation_changed.emit(False)
            self._update_controls()
            self.stopped.emit()
            if self._close_requested:
                self.close()

    def _receive_frame(self) -> None:
        if self.sender() is not self.worker or self._stopping:
            return
        frame = self.worker.take_frame()
        if frame is None:
            return
        self.canvas.set_image(
            bgr_to_qimage(frame.image),
            frame.parking_space_states,
            frame.plate_detections,
        )
        self._render_parking_summary(frame.parking_space_states)
        self._last_frame_at = time.monotonic()
        media = f" | {frame.media_time_s:.2f} giây video" if frame.media_time_s is not None else ""
        dropped = self.worker.dropped_frames
        tracked = sum(item.track_id is not None for item in frame.plate_detections)
        self.position_label.setText(
            f"Khung {frame.frame_index}{media}"
            f" | Biển số: {len(frame.plate_detections)} | Có ID: {tracked}"
            f" | Bỏ khung hiển thị: {dropped}"
        )
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(frame.frame_index)
        self._render_status()

    def _receive_status(self, status: StreamStatus, detail: str) -> None:
        if self.sender() is not self.worker or (self._stopping and status != StreamStatus.STOPPED):
            return
        self._status = status
        if status not in (StreamStatus.PLAYING, StreamStatus.PAUSED):
            self._clear_image(status.value)
            self._render_parking_summary()
        self._render_status(detail)

    def _render_status(self, detail: str = "") -> None:
        name = self._active.name if self._active else "Nguồn hình"
        overload = ""
        if self.worker and self.worker.dropped_frames:
            overload = " | Hiển thị quá tải: đã bỏ khung cũ, có thể bỏ lỡ sự kiện."
        self.status_label.setText(f"{name}: {self._status.value}. {detail}{overload}")

    def _stream_reset(self, _stream_id: str) -> None:
        if self.sender() is self.worker:
            self._clear_image("Đang nhận khung hình mới…")
            self._render_parking_summary()
            self._last_frame_at = 0
            self.candidate_list.clear()

    def _receive_candidate(self, candidate: EventCandidate) -> None:
        if self.sender() is not self.worker or self._stopping:
            return
        direction = "VÀO" if candidate.direction.value == "ENTRY" else "RA"
        media = (
            f" | video {candidate.media_time_s:.2f}s" if candidate.media_time_s is not None else ""
        )
        item = QListWidgetItem(
            f"{direction} — Biển số {candidate.confidence:.0%} — track #{candidate.track_id}{media}"
        )
        item.setData(Qt.ItemDataRole.UserRole, candidate)
        self.candidate_list.addItem(item)
        if self.candidate_list.count() > 50:
            self.candidate_list.takeItem(0)
        self.candidate_list.setCurrentItem(item)
        self._update_candidate_controls()

    def _update_candidate_controls(self, *_args) -> None:
        item = self.candidate_list.currentItem() if hasattr(self, "candidate_list") else None
        candidate = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.review_candidate_button.setEnabled(
            isinstance(candidate, EventCandidate) and not self._stopping
        )
        if isinstance(candidate, EventCandidate) and candidate.source_kind == SourceKind.MP4:
            self.review_candidate_button.setToolTip(
                "Chuyển ảnh từ MP4 sang vận hành để kiểm tra và xác nhận lượt xe."
            )
        else:
            self.review_candidate_button.setToolTip("")

    def _review_selected_candidate(self) -> None:
        item = self.candidate_list.currentItem()
        candidate = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(candidate, EventCandidate):
            return
        if self._stopping:
            return
        self.review_candidate_requested.emit(candidate)

    def _metadata(self, _fps: float, count: int) -> None:
        if self.sender() is self.worker:
            self.seek_slider.setRange(0, max(0, count - 1))

    def _check_health(self) -> None:
        if self.worker is None:
            return
        try:
            self.service.authorize(self.actor)
        except DomainError:
            self.stop_playback()
            self.status_label.setText("Tài khoản đã bị khóa hoặc đổi quyền. Hãy đăng nhập lại.")
            return
        if (
            self._active
            and self._active.kind == SourceKind.LIVE
            and self._last_frame_at
            and time.monotonic() - self._last_frame_at > self.options.stale_after_s
        ):
            self._clear_image("Hình quá hạn — trạng thái khu đỗ: KHÔNG XÁC ĐỊNH")
            self._render_parking_summary()
            self.status_label.setText(f"{self._active.name}: không có khung hình mới.")

    def _toggle_pause(self) -> None:
        if self.worker is not None and self._active.kind == SourceKind.MP4:
            self._paused = not self._paused
            self.worker.set_paused(self._paused)
            self.pause_button.setText("Tiếp tục" if self._paused else "Tạm dừng")

    def _seek(self) -> None:
        if self.worker is not None and self._active.kind == SourceKind.MP4:
            self._clear_image("Đang tua…")
            self._render_parking_summary()
            self.worker.seek(self.seek_slider.value())

    def _update_controls(self) -> None:
        running = self.worker is not None and not self._stopping
        is_file = self._active is not None and self._active.kind == SourceKind.MP4
        self.pause_button.setEnabled(running and is_file)
        self.seek_slider.setEnabled(running and is_file)
        self.stop_button.setEnabled(self.worker is not None)
        self.realtime_check.setEnabled(self.worker is None)
        if not running:
            self.pause_button.setText("Tạm dừng")

    def _refresh_space_selector(self) -> None:
        self.space_selector.blockSignals(True)
        self.space_selector.clear()
        for space in self._parking_spaces:
            self.space_selector.addItem(space.code, space.code)
        self.space_selector.blockSignals(False)
        self.remove_space_button.setEnabled(self.actor.is_admin and bool(self._parking_spaces))

    def _clear_image(self, message: str) -> None:
        self._active_polygon_code = None
        self.finish_polygon_button.setEnabled(False)
        self.canvas.clear_image(message)

    def _select_space(self, index: int) -> None:
        if index < 0:
            return
        code = self.space_selector.itemData(index)
        space = next((item for item in self._parking_spaces if item.code == code), None)
        if space is not None:
            self.space_code_input.setText(space.code)

    def _begin_polygon(self) -> None:
        if not self.actor.is_admin:
            return
        if self.purpose_combo.currentData() != SourcePurpose.PARKING:
            QMessageBox.warning(
                self,
                "Không phải camera khu đỗ",
                "Hãy chọn mục đích Khu đỗ trước khi vẽ polygon.",
            )
            return
        if self.canvas.image.isNull():
            QMessageBox.warning(
                self,
                "Chưa có hình xem trước",
                "Kết nối/xem thử camera khu đỗ trước khi vẽ polygon.",
            )
            return
        code = self.space_code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Thiếu mã ô", "Nhập mã ô trước khi vẽ.")
            return
        self._active_polygon_code = code
        self.canvas.begin_polygon()
        self.finish_polygon_button.setEnabled(True)

    def _polygon_finished(self, points: tuple[tuple[float, float], ...]) -> None:
        code = self._active_polygon_code
        self._active_polygon_code = None
        self.canvas.editable = self.actor.is_admin
        self.finish_polygon_button.setEnabled(False)
        if code is None:
            return
        if len(points) < 3:
            QMessageBox.warning(
                self,
                "Polygon chưa hợp lệ",
                "Bấm ít nhất 3 đỉnh trong vùng hình camera rồi lưu lại.",
            )
            return
        try:
            space = ParkingSpace(code, points)
            space.validate()
        except DomainError as exc:
            QMessageBox.warning(self, "Polygon chưa hợp lệ", str(exc))
            return
        normalized = code.casefold()
        self._parking_spaces = [
            existing for existing in self._parking_spaces if existing.code.casefold() != normalized
        ]
        self._parking_spaces.append(space)
        self.canvas.set_parking_spaces(tuple(self._parking_spaces))
        self._refresh_space_selector()
        self.space_selector.setCurrentIndex(self.space_selector.findData(code))
        self._render_parking_summary()

    def _remove_space(self) -> None:
        code = self.space_selector.currentData()
        if code is None:
            return
        self._parking_spaces = [space for space in self._parking_spaces if space.code != code]
        self.canvas.set_parking_spaces(tuple(self._parking_spaces))
        self._refresh_space_selector()
        self._render_parking_summary()

    def _render_parking_summary(self, states=None) -> None:  # noqa: ANN001
        if not hasattr(self, "parking_summary_label"):
            return
        config = self._active or self._selected
        if config is not None and config.purpose != SourcePurpose.PARKING:
            self.parking_summary_label.setText(
                "Trạng thái ô đỗ: nguồn này không phải camera khu đỗ."
            )
            return
        spaces = tuple(self._parking_spaces)
        if not spaces:
            self.parking_summary_label.setText("Trạng thái ô đỗ: chưa cấu hình ô nào.")
            return
        current = states if states is not None else self.canvas.parking_space_states
        normalized = {
            space.code: current.get(space.code, ParkingSpaceStatus.UNKNOWN) for space in spaces
        }
        counts = {
            status: sum(value == status for value in normalized.values())
            for status in ParkingSpaceStatus
        }
        details = " | ".join(f"{space.code}: {normalized[space.code].value}" for space in spaces)
        comparison = ""
        if self.open_session_count_provider is not None:
            now = time.monotonic()
            if now - self._last_open_count_refresh >= 5:
                try:
                    count = self.open_session_count_provider()
                    if type(count) is not int or count < 0:
                        raise ValueError("Số lượt đang gửi phải là số nguyên không âm.")
                    self._open_session_count = count
                    self._open_count_error = None
                except Exception as exc:
                    self._open_session_count = None
                    self._open_count_error = str(exc)
                self._last_open_count_refresh = now
            if self._open_count_error is not None:
                comparison = f" Không tải được số lượt đang gửi: {self._open_count_error}"
            elif self._open_session_count is not None:
                comparison = f" | Lượt đang gửi toàn bãi (đếm riêng): {self._open_session_count}"
                if counts[ParkingSpaceStatus.UNKNOWN] == 0:
                    difference = counts[ParkingSpaceStatus.OCCUPIED] - self._open_session_count
                    comparison += (
                        f" | Chênh lệch tham khảo (ô trong camera - lượt toàn bãi): {difference:+d}"
                    )
                else:
                    comparison += " | Còn ô không xác định nên chưa thể đối chiếu đầy đủ."
        self.parking_summary_label.setText(
            "Ô đỗ — "
            f"Trống: {counts[ParkingSpaceStatus.FREE]}, "
            f"Có xe: {counts[ParkingSpaceStatus.OCCUPIED]}, "
            f"Không xác định: {counts[ParkingSpaceStatus.UNKNOWN]}. "
            f"{details}{comparison}"
        )

    def _save_source(self) -> None:
        try:
            config = self.service.save_source(self.actor, self._draft())
            self.refresh_sources(config.id)
            self.source_feedback_label.setText(
                f"Đã lưu và chọn nguồn “{config.name}”. Nhấn Phát / Kết nối để áp dụng."
            )
        except (DomainError, ValueError) as exc:
            QMessageBox.warning(self, "Không lưu được cấu hình", str(exc))
        except Exception:
            QMessageBox.critical(self, "Lỗi lưu", "Không lưu được cấu hình. Dữ liệu đã rollback.")

    def _delete_source(self) -> None:
        if self._selected is None:
            return
        if (
            QMessageBox.question(
                self,
                "Xóa nguồn",
                "Xóa nguồn hình đã lưu?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.service.delete_source(self.actor, self._selected.id)
            self.refresh_sources()
        except DomainError as exc:
            QMessageBox.warning(self, "Không xóa được nguồn", str(exc))

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self._close_requested = True
            self.stop_playback()
            event.ignore()
        else:
            self.timer.stop()
            event.accept()
