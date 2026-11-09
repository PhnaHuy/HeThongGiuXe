"""Main Application Window with role-based navigation and operator session control."""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.plate_recognition import (
    PlateRecognitionService,
    PlateRecognitionUseCase,
)
from parking_app.application.source_service import SourceService
from parking_app.config.settings import AppSettings
from parking_app.domain.models import User
from parking_app.domain.plate import PlateRecognition
from parking_app.domain.video import SourceKind, VideoOptions, VisionOptions
from parking_app.domain.vision import EventCandidate
from parking_app.ui.audit_view import AuditLogWidget
from parking_app.ui.capacity_view import CapacityManagementWidget
from parking_app.ui.customer_view import CustomerManagementWidget
from parking_app.ui.dashboard_view import ParkingDashboardWidget
from parking_app.ui.exception_view import ExceptionManagementWidget
from parking_app.ui.parking_view import ParkingManagementWidget
from parking_app.ui.plate_recognition_worker import (
    PlateRecognitionWarmupWorker,
    PlateRecognitionWorker,
)
from parking_app.ui.source_view import SourceManagementWidget
from parking_app.ui.user_admin_view import UserManagementWidget


class MainWindow(QMainWindow):
    """Primary application window displaying role-filtered features."""

    logout_requested = Signal()
    window_closed = Signal()

    def __init__(
        self,
        current_user: User,
        auth_service: AuthService,
        customer_service: CustomerService,
        audit_service: AuditService,
        parent=None,  # noqa: ANN001
        parking_service: ParkingService | None = None,
        source_service: SourceService | None = None,
        video_options: VideoOptions | None = None,
        plate_vision_options: VisionOptions | None = None,
        plate_recognition_service: PlateRecognitionUseCase | None = None,
        warmup_plate_recognition: bool = False,
    ) -> None:
        super().__init__(parent)
        self.current_user = current_user
        self.auth_service = auth_service
        self.customer_service = customer_service
        self.audit_service = audit_service
        self.parking_service = parking_service
        self.source_service = source_service
        defaults = AppSettings()
        self.video_options = video_options or defaults.video_options
        self.plate_vision_options = plate_vision_options or defaults.plate_vision_options
        self.source_widget = None
        self._logout_pending = False
        self._close_pending = False
        self._plate_recognition_service = plate_recognition_service or PlateRecognitionService(
            defaults.plate_recognition_options,
            plate_vision_options=self.plate_vision_options,
        )
        self._plate_worker: PlateRecognitionWorker | None = None
        self._ocr_warmup_worker: PlateRecognitionWarmupWorker | None = None
        self._plate_request_queue: deque[tuple[str, tuple[bytes, ...]]] = deque()

        self.setWindowTitle("Bãi xe thông minh — Quản lý vận hành")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 820)
        self._init_ui()
        if warmup_plate_recognition:
            QTimer.singleShot(0, self._start_ocr_warmup)

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 15, 20, 12)
        main_layout.setSpacing(12)

        header = QWidget()
        header.setObjectName("appHeader")
        header_bar = QHBoxLayout(header)
        header_bar.setContentsMargins(18, 12, 14, 12)
        header_bar.setSpacing(12)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(1)
        app_title = QLabel("BÃI XE THÔNG MINH")
        app_title.setObjectName("appTitle")
        title_font = QFont()
        title_font.setPointSize(17)
        title_font.setBold(True)
        app_title.setFont(title_font)
        subtitle = QLabel("QUẢN LÝ VẬN HÀNH · THỊ GIÁC MÁY TÍNH")
        subtitle.setObjectName("appSubtitle")
        title_stack.addWidget(app_title)
        title_stack.addWidget(subtitle)
        header_bar.addLayout(title_stack)

        header_bar.addStretch()

        user_info = QLabel(
            f"{self.current_user.full_name}  ·  {self.current_user.username}"
            f"  ·  {self.current_user.role.display_name}"
        )
        user_info.setObjectName("userInfo")
        user_info.setTextFormat(Qt.TextFormat.PlainText)
        header_bar.addWidget(user_info)

        self.logout_btn = QPushButton("Đăng xuất")
        self.logout_btn.setObjectName("dangerButton")
        self.logout_btn.clicked.connect(self._handle_logout)
        header_bar.addWidget(self.logout_btn)

        main_layout.addWidget(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("headerDivider")
        main_layout.addWidget(line)

        # Role-based Tabbed Interface
        self.tabs = QTabWidget()
        if self.source_service is not None:
            self.source_widget = SourceManagementWidget(
                self.source_service,
                self.current_user,
                self.video_options,
                parent=self,
                open_session_count_provider=(
                    lambda: self.parking_service.get_capacity_summary().total_active
                )
                if self.parking_service is not None
                else None,
                plate_vision_options=self.plate_vision_options,
            )
            self.source_widget.stopped.connect(self._source_stopped)
            self.source_widget.simulation_changed.connect(self._set_simulation)
            self.source_widget.review_candidate_requested.connect(self._review_candidate)
            self.source_widget.playback_started.connect(self._stop_operation_camera)
            self.tabs.addTab(self.source_widget, "Nguồn hình — Camera / MP4")

        if self.parking_service is not None:
            self.parking_widget = ParkingManagementWidget(
                self.parking_service,
                self.current_user,
                parent=self,
                source_service=self.source_service,
                video_options=self.video_options,
                plate_vision_options=self.plate_vision_options,
            )
            self.parking_widget.plate_recognition_requested.connect(self._start_plate_recognition)
            self.parking_widget.camera_candidate_detected.connect(self._review_candidate)
            if self.parking_widget.camera_panel is not None:
                self.parking_widget.camera_panel.simulation_changed.connect(self._set_simulation)
                self.parking_widget.camera_panel.playback_started.connect(self._stop_source_preview)
                self.parking_widget.camera_panel.stopped.connect(self._source_stopped)
            self.tabs.addTab(self.parking_widget, "Vận hành bãi xe")

            if self.current_user.is_manager:
                self.dashboard_widget = ParkingDashboardWidget(
                    self.parking_service,
                    self.current_user,
                    parent=self,
                )
                self.dashboard_widget.operations_idle.connect(self._background_operations_idle)
                self.tabs.addTab(self.dashboard_widget, "Tổng quan và thống kê")
                self.exception_widget = ExceptionManagementWidget(
                    self.audit_service,
                    self.parking_service,
                    self.current_user,
                    parent=self,
                )
                self.tabs.addTab(self.exception_widget, "Theo dõi bất thường")
                self.parking_widget.session_state_changed.connect(self.dashboard_widget.refresh)
                self.exception_widget.case_updated.connect(self.dashboard_widget.refresh)

            if self.current_user.is_admin:
                self.capacity_widget = CapacityManagementWidget(
                    self.parking_service,
                    self.current_user,
                    parent=self,
                )
                self.capacity_widget.capacity_updated.connect(self.parking_widget.refresh)
                if self.current_user.is_manager:
                    self.capacity_widget.capacity_updated.connect(self.dashboard_widget.refresh)
                self.tabs.addTab(self.capacity_widget, "Cấu hình sức chứa")

        # Customer & Vehicle Management (Available to Staff, Manager, Admin)
        self.customer_widget = CustomerManagementWidget(
            self.customer_service, self.current_user, parent=self
        )
        self.tabs.addTab(self.customer_widget, "Quản lý Khách hàng & Phương tiện")

        # Tab 2: User Account Administration (Admin only)
        if self.current_user.is_admin:
            self.user_admin_widget = UserManagementWidget(
                self.auth_service, self.current_user, parent=self
            )
            self.tabs.addTab(self.user_admin_widget, "Quản lý Tài khoản (Admin)")

        # Tab 3: System Audit Trail (Manager and Admin)
        if self.current_user.is_manager:
            self.audit_widget = AuditLogWidget(self.audit_service, self.current_user, parent=self)
            self.tabs.addTab(self.audit_widget, "Nhật ký Hoạt động (Audit)")

        main_layout.addWidget(self.tabs)

        # Status Bar
        status_bar = QStatusBar(self)
        status_bar.showMessage(
            "AI chỉ đưa ra đề xuất · Nhân viên kiểm tra và xác nhận mọi lượt xe."
        )
        self.setStatusBar(status_bar)

    def _handle_logout(self) -> None:
        self._logout_pending = True
        self.close()

    def _stop_source_preview(self) -> None:
        if self.source_widget is not None:
            self.source_widget.stop_playback()

    def _stop_operation_camera(self) -> None:
        if self.parking_service is not None and self.parking_widget.camera_panel is not None:
            self.parking_widget.camera_panel.stop_playback()

    def _set_simulation(self, active: bool) -> None:
        if self.parking_service is not None:
            self.parking_service.set_operation_source(SourceKind.MP4 if active else SourceKind.LIVE)
            self.parking_widget.setEnabled(True)
            self.parking_widget.setToolTip(
                "MP4: có thể kiểm tra và xác nhận lượt xe vào/ra." if active else ""
            )

    def _review_candidate(self, candidate: EventCandidate) -> None:
        if self.parking_service is None:
            return
        self.parking_widget.stage_event_candidate(candidate)
        self.tabs.setCurrentWidget(self.parking_widget)
        self._run_next_plate_request()

    def _start_ocr_warmup(self) -> None:
        if self._ocr_warmup_worker is not None or self._close_pending:
            return
        worker = PlateRecognitionWarmupWorker(self._plate_recognition_service, parent=self)
        self._ocr_warmup_worker = worker
        worker.completed.connect(self._ocr_warmup_completed)
        worker.failed.connect(self._ocr_warmup_failed)
        worker.finished.connect(self._ocr_warmup_finished)
        if self.parking_service is not None:
            self.parking_widget.set_ocr_runtime_status(
                "Đang khởi tạo PaddleOCR nền; có thể nhập biển thủ công trong lúc chờ."
            )
        worker.start()

    def _ocr_warmup_completed(self) -> None:
        if self.parking_service is not None:
            self.parking_widget.set_ocr_runtime_status("PaddleOCR đã sẵn sàng.")

    def _ocr_warmup_failed(self, message: str) -> None:
        if self.parking_service is not None:
            self.parking_widget.set_ocr_runtime_status(
                f"PaddleOCR chưa sẵn sàng: {message}. Có thể nhập biển thủ công."
            )

    def _ocr_warmup_finished(self) -> None:
        worker = self.sender()
        if worker is not self._ocr_warmup_worker:
            return
        self._ocr_warmup_worker = None
        worker.deleteLater()
        if self._close_pending:
            self.close()

    def _start_plate_recognition(self, candidate_id: str, source_images: tuple[bytes, ...]) -> None:
        if len(self._plate_request_queue) >= 10:
            if hasattr(self, "parking_widget"):
                self.parking_widget.stage_plate_recognition_error(
                    candidate_id,
                    "Hàng đợi OCR đang đầy; vui lòng chờ rồi thử lại.",
                )
            return
        self._plate_request_queue.append((candidate_id, source_images))
        if self._plate_worker is not None and self._plate_worker.isRunning():
            if hasattr(self, "parking_widget"):
                self.parking_widget.stage_plate_recognition_pending(candidate_id)
            return
        self._run_next_plate_request()

    def _run_next_plate_request(self) -> None:
        if self._plate_worker is not None or not self._plate_request_queue or self._close_pending:
            return
        candidate_id, images = self._plate_request_queue.popleft()
        worker = PlateRecognitionWorker(
            candidate_id,
            images,
            self._plate_recognition_service,
            parent=self,
        )
        self._plate_worker = worker
        worker.completed.connect(self._plate_recognition_completed)
        worker.failed.connect(self._plate_recognition_failed)
        worker.finished.connect(self._plate_worker_finished)
        worker.start()

    def _plate_recognition_completed(
        self,
        candidate_id: str,
        result: PlateRecognition,
    ) -> None:
        if hasattr(self, "parking_widget"):
            self.parking_widget.stage_plate_recognition(candidate_id, result)

    def _plate_recognition_failed(self, candidate_id: str, message: str) -> None:
        if hasattr(self, "parking_widget"):
            self.parking_widget.stage_plate_recognition_error(candidate_id, message)

    def _plate_worker_finished(self) -> None:
        worker = self.sender()
        if worker is not self._plate_worker:
            return
        self._plate_worker = None
        worker.deleteLater()
        if self._close_pending and not self._plate_request_queue:
            self.close()
            return
        self._run_next_plate_request()

    def _source_stopped(self) -> None:
        if self._close_pending:
            self.close()

    def _background_operations_idle(self) -> None:
        if self._close_pending:
            self.close()

    def closeEvent(self, event) -> None:
        if (
            self.parking_service is not None
            and self.parking_widget.camera_panel is not None
            and self.parking_widget.camera_panel.worker is not None
        ):
            self._close_pending = True
            self._plate_request_queue.clear()
            self.parking_widget.camera_panel.shutdown()
            event.ignore()
            return
        if self.source_widget is not None and self.source_widget.worker is not None:
            self._close_pending = True
            self._plate_request_queue.clear()
            self.source_widget.stop_playback()
            event.ignore()
            return
        if self._ocr_warmup_worker is not None and self._ocr_warmup_worker.isRunning():
            self._close_pending = True
            event.ignore()
            return
        if self._plate_worker is not None and self._plate_worker.isRunning():
            self._close_pending = True
            self._plate_request_queue.clear()
            event.ignore()
            return
        if hasattr(self, "dashboard_widget") and self.dashboard_widget.has_running_operations():
            self._close_pending = True
            event.ignore()
            return
        if self.source_widget is not None:
            self.source_widget.timer.stop()
        close_ocr = getattr(self._plate_recognition_service, "close", None)
        if callable(close_ocr):
            close_ocr()
        event.accept()
        if self._logout_pending:
            self.auth_service.record_logout(self.current_user)
            self.logout_requested.emit()
        else:
            self.window_closed.emit()
