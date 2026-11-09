"""Camera capture and manual entry/exit selection inside the operation workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.source_service import SourceService
from parking_app.domain.exceptions import DomainError
from parking_app.domain.models import User
from parking_app.domain.video import (
    SourceConfig,
    SourcePurpose,
    StreamStatus,
    VideoOptions,
    VisionOptions,
)
from parking_app.infrastructure.vision.plate_detector import PlateTracker, YOLOPlateDetector
from parking_app.ui.video_canvas import VideoCanvas, bgr_to_qimage
from parking_app.ui.video_worker import VideoWorker


class OperationCameraPanel(QWidget):
    candidate_detected = Signal(object)
    simulation_changed = Signal(bool)
    playback_started = Signal()
    stopped = Signal()

    def __init__(
        self,
        service: SourceService,
        actor: User,
        video_options: VideoOptions,
        plate_vision_options: VisionOptions,
        *,
        source_factory: Callable | None = None,
        plate_detector_factory: Callable[[VisionOptions], PlateTracker] = YOLOPlateDetector,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.actor = actor
        self.video_options = video_options
        self.plate_vision_options = plate_vision_options
        self.source_factory = source_factory
        self.plate_detector_factory = plate_detector_factory
        self.worker: VideoWorker | None = None
        self._pending: tuple[SourceConfig, SourcePurpose] | None = None
        self._stopping = False

        group = QGroupBox("Nhận diện biển số — chọn thao tác")
        layout = QVBoxLayout(group)
        controls = QHBoxLayout()
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(200)
        controls.addWidget(self.source_combo, 1)
        self.entry_button = QPushButton("Xe vào")
        self.entry_button.setObjectName("primaryButton")
        self.entry_button.clicked.connect(lambda: self._start(SourcePurpose.ENTRY))
        controls.addWidget(self.entry_button)
        self.exit_button = QPushButton("Xe ra")
        self.exit_button.clicked.connect(lambda: self._start(SourcePurpose.EXIT))
        controls.addWidget(self.exit_button)
        self.stop_button = QPushButton("Dừng")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_playback)
        controls.addWidget(self.stop_button)
        self.refresh_button = QPushButton("Tải lại camera")
        self.refresh_button.clicked.connect(self.refresh_sources)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)

        preview_row = QHBoxLayout()
        self.canvas = VideoCanvas()
        self.canvas.setMinimumSize(320, 180)
        self.canvas.setMaximumHeight(210)
        preview_row.addWidget(self.canvas, 1)
        self.status_label = QLabel("Chọn camera, sau đó nhấn Xe vào hoặc Xe ra.")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(230)
        preview_row.addWidget(self.status_label)
        layout.addLayout(preview_row)
        self.ocr_status_label = QLabel("OCR sẽ được khởi tạo nền sau khi đăng nhập.")
        self.ocr_status_label.setWordWrap(True)
        layout.addWidget(self.ocr_status_label)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(group)
        self.refresh_sources()

    def set_ocr_runtime_status(self, message: str) -> None:
        self.ocr_status_label.setText(message)

    def refresh_sources(self) -> None:
        try:
            sources = [
                config
                for config in self.service.list_sources(self.actor)
                if config.purpose != SourcePurpose.PARKING
            ]
        except DomainError as exc:
            self.status_label.setText(f"Không tải được danh sách camera: {exc}")
            return
        current_id = self.source_combo.currentData().id if self.source_combo.currentData() else None
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for config in sources:
            kind = "MP4" if config.kind.value == "MP4" else "Camera"
            self.source_combo.addItem(f"{config.name} ({kind})", config)
        if current_id:
            index = next(
                (
                    index
                    for index in range(self.source_combo.count())
                    if self.source_combo.itemData(index).id == current_id
                ),
                -1,
            )
            if index >= 0:
                self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        if not sources:
            self.status_label.setText(
                "Chưa có camera cổng. Quản trị viên cần cấu hình nguồn trước."
            )

    def _start(self, purpose: SourcePurpose) -> None:
        config = self.source_combo.currentData()
        if not isinstance(config, SourceConfig):
            self.status_label.setText("Chọn một camera cổng đã lưu trước khi bắt đầu.")
            return
        config = replace(config, purpose=purpose)
        self._pending = (config, purpose)
        if self.worker is not None:
            self._stopping = True
            self.worker.stop()
            self.status_label.setText("Đang chuyển thao tác camera…")
            return
        self._start_pending()

    def _start_pending(self) -> None:
        if self._pending is None:
            return
        config, purpose = self._pending
        self._pending = None
        self._stopping = False
        self.canvas.clear_image("Đang kết nối camera…")
        self.status_label.setText(
            f"Đang quét biển số để xác nhận xe {'vào' if purpose == SourcePurpose.ENTRY else 'ra'}."
        )
        kwargs = {
            "realtime": True,
            "plate_vision_options": self.plate_vision_options,
            "plate_detector_factory": self.plate_detector_factory,
        }
        if self.source_factory is not None:
            kwargs["source_factory"] = self.source_factory
        worker = VideoWorker(config, self.video_options, **kwargs)
        self.worker = worker
        worker.frame_available.connect(self._receive_frame)
        worker.status_changed.connect(self._receive_status)
        worker.event_candidate.connect(self.candidate_detected)
        worker.finished.connect(self._finished)
        self.stop_button.setEnabled(True)
        self.simulation_changed.emit(config.kind.value == "MP4")
        self.playback_started.emit()
        worker.start()

    def _receive_frame(self) -> None:
        if self.sender() is not self.worker or self._stopping:
            return
        frame = self.worker.take_frame()
        if frame is not None:
            self.canvas.set_image(
                bgr_to_qimage(frame.image),
                frame.parking_space_states,
                frame.plate_detections,
            )

    def _receive_status(self, status: StreamStatus, detail: str) -> None:
        if self.sender() is self.worker and not self._stopping:
            suffix = f" {detail}" if detail else ""
            self.status_label.setText(f"{status.value}.{suffix}")

    def stop_playback(self) -> None:
        self._pending = None
        self.canvas.clear_image("Đã dừng camera")
        if self.worker is None:
            self.stop_button.setEnabled(False)
            return
        self._stopping = True
        self.status_label.setText("Đang dừng camera…")
        self.worker.stop()

    def _finished(self) -> None:
        if self.sender() is not self.worker:
            return
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self._stopping = False
        self.stop_button.setEnabled(False)
        self.simulation_changed.emit(False)
        self.stopped.emit()
        if self._pending is not None:
            self._start_pending()

    def shutdown(self) -> None:
        self._pending = None
        if self.worker is not None:
            self._stopping = True
            self.worker.stop()
