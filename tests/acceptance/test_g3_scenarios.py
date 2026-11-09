"""G3 UI/worker acceptance with generated media and simulated camera failures."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.source_service import SourceService
from parking_app.application.video_source import VideoError
from parking_app.domain.enums import UserStatus
from parking_app.domain.video import GateLine, SourceConfig, SourceKind, StreamStatus, VideoOptions
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.orm_models import UserModel
from parking_app.ui.main_window import MainWindow
from parking_app.ui.source_view import SourceManagementWidget
from parking_app.ui.video_canvas import VideoCanvas, bgr_to_qimage
from parking_app.ui.video_worker import VideoWorker


class EmptyDetector:
    def __init__(self, _options):
        pass

    def detect(self, _image):
        return ()

    def reset(self):
        pass


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_until(qapp, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate(), "Timed out waiting for video state"


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "demo.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 96))
    assert writer.isOpened()
    for i in range(30):
        writer.write(np.full((96, 160, 3), i * 7, np.uint8))
    writer.release()
    return SourceConfig("demo", "Video mẫu", SourceKind.MP4, str(path), line=GateLine())


def test_mp4_complete_mode_pause_seek_and_reset(qapp, video):
    worker = VideoWorker(video, realtime=False, detector_factory=EmptyDetector)
    frames, resets, statuses = [], [], []

    def collect():
        frame = worker.take_frame()
        if frame is not None:
            frames.append(frame)
            if len(frames) == 4:
                worker.set_paused(True)

    worker.frame_available.connect(collect)
    worker.stream_reset.connect(resets.append)
    worker.status_changed.connect(lambda status, _detail: statuses.append(status))
    try:
        worker.start()
        wait_until(qapp, lambda: StreamStatus.PAUSED in statuses)
        assert [f.frame_index for f in frames[:4]] == [0, 1, 2, 3]
        worker.seek(12)
        wait_until(qapp, lambda: len(resets) == 2 and frames[-1].frame_index == 12)
        assert frames[0].stream_id != frames[-1].stream_id
        assert frames[-1].media_time_s >= 1.1
        assert worker.dropped_frames == 0
        worker.set_paused(False)
        wait_until(qapp, lambda: not worker.isRunning())
        assert StreamStatus.EOF in statuses
        assert [f.frame_index for f in frames if f.stream_id == resets[-1]] == list(range(12, 30))
    finally:
        worker.stop()
        assert worker.wait(4000)


class FakeCamera:
    fps = 100
    frame_count = 0

    def __init__(self, fail=False):
        self.fail = fail
        self.index = 0
        self.closed = False

    def open(self):
        pass

    def read(self):
        time.sleep(0.005)
        if self.fail and self.index == 1:
            raise VideoError("Simulated disconnect")
        index = self.index
        self.index += 1
        return index, None, np.zeros((96, 160, 3), np.uint8)

    def close(self):
        self.closed = True


def test_camera_reconnect_resets_and_bounds_preview_buffer(qapp):
    cameras, resets, statuses = [], [], []

    def factory(*args):
        camera = FakeCamera(fail=not cameras)
        cameras.append(camera)
        return camera

    worker = VideoWorker(
        SourceConfig("cam", "Camera giả lập", SourceKind.LIVE, "0"),
        VideoOptions(reconnect_delay_s=0.02),
        source_factory=factory,
        detector_factory=EmptyDetector,
    )
    worker.stream_reset.connect(resets.append)
    worker.status_changed.connect(lambda status, _detail: statuses.append(status))
    try:
        worker.start()
        wait_until(qapp, lambda: worker.dropped_frames >= 4)
        assert StreamStatus.DISCONNECTED in statuses
        assert len(resets) >= 3  # Start, invalidate disconnected stream, reconnect.
        assert len(set(resets)) == len(resets)
        frame = worker.take_frame()
        assert frame.stream_id == resets[-1]
        assert frame.frame_index >= 3
    finally:
        worker.stop()
        assert worker.wait(3000)
    assert all(camera.closed for camera in cameras)
    assert worker.take_frame() is None


def test_new_source_has_no_fixed_camera_url(qapp, session_manager, seeded_users):
    service = SourceService(session_manager)
    widget = SourceManagementWidget(service, seeded_users["admin"], detector_factory=EmptyDetector)
    try:
        assert widget.endpoint_input.text() == ""
        config = SourceConfig("cam", "Camera", SourceKind.LIVE, "rtsp://host:8554/live")
        service.save_source(seeded_users["admin"], config)
        widget.refresh_sources(config.id)
        assert widget.endpoint_input.text() == config.endpoint
        widget._create_new_source()
        assert widget.endpoint_input.text() == ""
    finally:
        widget.close()


def test_ui_preview_save_line_switch_source_and_close(qapp, session_manager, seeded_users, video):
    service = SourceService(session_manager)
    widget = SourceManagementWidget(service, seeded_users["admin"], detector_factory=EmptyDetector)
    widget.resize(1100, 700)
    widget.show()
    try:
        widget._load_config(video)
        assert not widget.delete_source_button.isEnabled()
        widget.start_playback(video)
        wait_until(qapp, lambda: not widget.canvas.image.isNull())
        assert "THỬ NGHIỆM" in widget.mode_label.text()
        widget._toggle_pause()
        wait_until(qapp, lambda: widget._status == StreamStatus.PAUSED)
        rect = widget.canvas.image_rect()
        a = QPoint(int(rect.x() + rect.width() * 0.2), int(rect.y() + rect.height() * 0.4))
        b = QPoint(int(rect.x() + rect.width() * 0.8), int(rect.y() + rect.height() * 0.4))
        QTest.mousePress(widget.canvas, Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseRelease(widget.canvas, Qt.MouseButton.LeftButton, pos=b)
        widget.reverse_check.setChecked(True)
        widget._save_source()
        wait_until(qapp, lambda: widget.worker is None)
        stored = service.list_sources(seeded_users["admin"])[0]
        assert stored.line.entry_positive is False
        assert stored.line.y1 == pytest.approx(0.4, abs=0.01)
        widget.start_playback(stored)
        wait_until(qapp, lambda: not widget.canvas.image.isNull())
        old = widget.worker
        widget.start_playback(video)
        wait_until(qapp, lambda: widget.worker is not None and widget.worker is not old)
        widget.stop_playback()
        wait_until(qapp, lambda: widget.worker is None)
        assert widget.canvas.image.isNull()
    finally:
        widget.stop_playback()
        wait_until(qapp, lambda: widget.worker is None)
        widget.close()


def test_window_mp4_allows_operations_and_close_stops_worker(
    qapp,
    session_manager,
    seeded_users,
    tmp_path,
    video,
):
    service = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    window = MainWindow(
        seeded_users["staff"],
        AuthService(session_manager),
        CustomerService(session_manager),
        AuditService(session_manager),
        parking_service=service,
        source_service=SourceService(session_manager),
    )
    window.source_widget.detector_factory = EmptyDetector
    window.show()
    try:
        window.source_widget.start_playback(video)
        wait_until(qapp, lambda: not window.source_widget.canvas.image.isNull())
        assert service.operation_source_kind == SourceKind.MP4
        assert window.parking_widget.isEnabled()
        window.close()
        wait_until(qapp, lambda: window.source_widget.worker is None and not window.isVisible())
        assert service.operation_source_kind == SourceKind.LIVE
    finally:
        window.source_widget.stop_playback()
        wait_until(qapp, lambda: window.source_widget.worker is None)
        window.close()


def test_image_adapter_owns_pixels_and_letterbox_ignores_outside_click(qapp):
    pixels = np.zeros((100, 200, 3), np.uint8)
    image = bgr_to_qimage(pixels)
    pixels[:] = 255
    assert image.pixelColor(0, 0).red() == 0
    canvas = VideoCanvas()
    canvas.resize(600, 500)
    canvas.editable = True
    canvas.set_image(image)
    canvas.show()
    qapp.processEvents()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 250))
    assert canvas.line is None
    canvas.close()


def test_locked_account_stops_open_preview(qapp, session_manager, seeded_users, video):
    widget = SourceManagementWidget(
        SourceService(session_manager), seeded_users["staff"], detector_factory=EmptyDetector
    )
    try:
        widget.start_playback(video)
        wait_until(qapp, lambda: not widget.canvas.image.isNull())
        with session_manager.session() as session:
            session.get(UserModel, seeded_users["staff"].id).status = UserStatus.LOCKED
        widget._check_health()
        wait_until(qapp, lambda: widget.worker is None)
        assert widget.canvas.image.isNull()
    finally:
        widget.stop_playback()
        wait_until(qapp, lambda: widget.worker is None)
        widget.close()


def test_stale_live_image_is_cleared(qapp, session_manager, seeded_users, monkeypatch):
    class NoWorker:
        pass

    widget = SourceManagementWidget(
        SourceService(session_manager), seeded_users["staff"], detector_factory=EmptyDetector
    )
    widget.worker = NoWorker()
    widget._active = SourceConfig("cam", "Cổng mẫu", SourceKind.LIVE, "0")
    widget._last_frame_at = time.monotonic() - 10
    widget.canvas.set_image(bgr_to_qimage(np.zeros((96, 160, 3), np.uint8)))
    widget._check_health()
    assert widget.canvas.image.isNull()
    assert "KHÔNG XÁC ĐỊNH" in widget.canvas.message
    widget.worker = None
    widget.close()
