import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMessageBox

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.source_service import SourceService
from parking_app.domain.enums import ParkingStatus, VehicleType
from parking_app.domain.plate import PlateRecognition
from parking_app.domain.video import GateLine, SourceConfig, SourceKind, VisionOptions
from parking_app.domain.vision import EventCandidate, GateDirection, VehicleDetection
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.vision.yolo_detector import VisionError
from parking_app.ui.main_window import MainWindow
from parking_app.ui.parking_view import ParkingManagementWidget
from parking_app.ui.source_view import SourceManagementWidget
from parking_app.ui.video_worker import VideoWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


class SequenceSource:
    def __init__(self, _config, _options, _cancelled):
        self.frames = [0, 0, 0, 255, 255, 255]
        self.index = 0
        self.fps = 30
        self.frame_count = len(self.frames)

    def open(self):
        self.index = 0

    def read(self):
        if self.index >= len(self.frames):
            return None
        index = self.index
        self.index += 1
        image = np.full((100, 100, 3), self.frames[index], dtype=np.uint8)
        return index, index / self.fps, image

    def seek(self, frame_index):
        self.index = frame_index

    def close(self):
        pass


class EmptyPlateRecognizer:
    def recognize(self, images):
        return PlateRecognition((), None, None, None, len(images))


class MovingVehicleDetector:
    def __init__(self, _options):
        self.index = 0

    def detect(self, _image):
        center_y = 0.3 if self.index < 3 else 0.7
        self.index += 1
        return (
            VehicleDetection(
                x1=0.25,
                y1=center_y - 0.25,
                x2=0.75,
                y2=center_y + 0.25,
                confidence=0.93,
                vehicle_type=VehicleType.CAR,
                track_id=12,
            ),
        )

    def reset(self):
        self.index = 0


def wait_until(qapp, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate(), "Timed out waiting for G4 processing"


def candidate(direction, source_kind=SourceKind.LIVE):
    ok, image = cv2.imencode(
        ".jpg",
        np.full((60, 80, 3), 100, dtype=np.uint8),
    )
    assert ok
    return EventCandidate(
        id="event-1",
        source_id="gate-1",
        source_name="Cổng chính",
        source_kind=source_kind,
        stream_id="stream-1",
        track_id=12,
        direction=direction,
        vehicle_type=VehicleType.CAR,
        confidence=0.93,
        observed_at=datetime.now(UTC),
        media_time_s=1.2 if source_kind == SourceKind.MP4 else None,
        image_data=image.tobytes(),
    )


def test_video_worker_produces_directional_event_with_vehicle_evidence(qapp):
    config = SourceConfig(
        "gate-1",
        "Cổng chính",
        SourceKind.MP4,
        "demo.mp4",
        line=GateLine(),
    )
    options = VisionOptions(model_path=Path("unused.pt"))
    worker = VideoWorker(
        config,
        realtime=False,
        source_factory=SequenceSource,
        vision_options=options,
        detector_factory=MovingVehicleDetector,
    )
    candidates = []
    frames = []

    def take_frame():
        frame = worker.take_frame()
        if frame is not None:
            frames.append(frame)

    worker.event_candidate.connect(candidates.append)
    worker.frame_available.connect(take_frame)
    worker.start()
    wait_until(qapp, lambda: not worker.isRunning())
    assert worker.wait(1000)

    assert len(candidates) == 1
    event = candidates[0]
    assert event.direction == GateDirection.ENTRY
    assert event.vehicle_type == VehicleType.CAR
    assert event.track_id == 12
    assert event.source_kind == SourceKind.MP4
    assert 1 <= len(event.vehicle_image_samples) <= 5
    cropped = cv2.imdecode(np.frombuffer(event.image_data, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert cropped.shape == (50, 50, 3)
    assert frames and frames[-1].detections[0].track_id == 12


@pytest.mark.parametrize("source_kind", [SourceKind.LIVE, SourceKind.MP4])
def test_candidate_opens_operator_review_but_does_not_create_entry_automatically(
    qapp,
    session_manager,
    seeded_users,
    tmp_path,
    monkeypatch,
    source_kind,
):
    parking = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    auth = AuthService(session_manager)
    customers = CustomerService(session_manager)
    audit = AuditService(session_manager)
    sources = SourceService(session_manager)
    window = MainWindow(
        seeded_users["staff"],
        auth,
        customers,
        audit,
        parking_service=parking,
        source_service=sources,
        vision_options=VisionOptions(model_path=tmp_path / "unused.pt"),
        plate_recognition_service=EmptyPlateRecognizer(),
    )
    window._set_simulation(source_kind == SourceKind.MP4)
    event = candidate(GateDirection.ENTRY, source_kind)
    window._review_candidate(event)
    assert window.tabs.currentWidget() is window.parking_widget
    assert window.parking_widget.entry_plate_input.text() == ""
    assert not window.parking_widget.entry_image_preview.pixmap().isNull()
    assert parking.list_active_sessions() == []

    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    window.parking_widget._create_entry()
    active = parking.list_active_sessions()
    assert len(active) == 1
    assert active[0].snapshot_plate.startswith("UNREADABLE_")
    assert active[0].entry_image_path is not None
    wait_until(qapp, lambda: window._plate_worker is None)
    window.close()


@pytest.mark.parametrize("source_kind", [SourceKind.LIVE, SourceKind.MP4])
def test_exit_candidate_requires_manual_session_selection_and_confirmation(
    qapp,
    session_manager,
    seeded_users,
    tmp_path,
    monkeypatch,
    source_kind,
):
    storage = EvidenceStorage(tmp_path / "evidence")
    parking = ParkingService(session_manager, storage)
    stay = parking.create_entry(seeded_users["staff"], "51A12345", VehicleType.CAR)
    widget = ParkingManagementWidget(parking, seeded_users["staff"])
    parking.set_operation_source(source_kind)
    widget.stage_event_candidate(candidate(GateDirection.EXIT, source_kind))

    assert widget.selected_session_id is None
    assert parking.get_session(stay.id).status == ParkingStatus.DANG_GUI
    assert not widget.exit_image_preview.pixmap().isNull()

    widget.active_table.selectRow(0)
    assert widget.selected_session_id == stay.id
    assert not widget.exit_image_preview.pixmap().isNull()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    widget._close_exit()
    assert parking.get_session(stay.id).status == ParkingStatus.DA_RA
    widget.close()


def test_mp4_candidates_can_be_sent_to_operator_review(
    qapp,
    session_manager,
    seeded_users,
):
    widget = SourceManagementWidget(
        SourceService(session_manager),
        seeded_users["admin"],
        detector_factory=MovingVehicleDetector,
    )
    item = QListWidgetItem("MP4 test event")
    item.setData(
        Qt.ItemDataRole.UserRole,
        candidate(GateDirection.ENTRY, source_kind=SourceKind.MP4),
    )
    widget.candidate_list.addItem(item)
    widget.candidate_list.setCurrentItem(item)
    widget._update_candidate_controls()
    assert widget.review_candidate_button.isEnabled()
    reviewed = []
    widget.review_candidate_requested.connect(reviewed.append)
    widget._review_selected_candidate()
    assert reviewed == [item.data(Qt.ItemDataRole.UserRole)]
    widget.close()


def test_model_start_failure_is_reported_without_opening_source(qapp, tmp_path):
    opened = []

    def missing_model(_options):
        raise VisionError("Model cục bộ không tồn tại.")

    def source_factory(*args):
        opened.append(True)
        return SequenceSource(*args)

    worker = VideoWorker(
        SourceConfig("cam", "Camera", SourceKind.LIVE, "0"),
        source_factory=source_factory,
        vision_options=VisionOptions(model_path=tmp_path / "missing.pt"),
        detector_factory=missing_model,
    )
    statuses = []
    worker.status_changed.connect(lambda status, detail: statuses.append((status, detail)))
    worker.start()
    wait_until(qapp, lambda: not worker.isRunning())
    assert worker.wait(1000)
    assert opened == []
    assert statuses and statuses[-1][1] == "Model cục bộ không tồn tại."


def test_live_line_edit_applies_without_restarting_and_clears_crossing_history(qapp):
    from dataclasses import replace

    worker = VideoWorker(
        SourceConfig("cam", "Camera", SourceKind.LIVE, "0"),
        vision_options=VisionOptions(model_path=Path("unused.pt")),
    )
    detector = MovingVehicleDetector(None)
    above = detector.detect(None)
    below = (replace(above[0], y1=0.55, y2=0.95),)
    assert worker._crossing_events(above, 0) == []
    worker.set_gate_line(GateLine())
    assert worker._crossing_events(above, 1) == []
    assert worker._crossing_events(above, 2) == []
    assert worker._crossing_events(below, 3) == []
    assert worker._crossing_events(below, 4)[0][1] == GateDirection.ENTRY
    worker.set_gate_line(GateLine(entry_positive=False))
    assert worker._crossing_events(above, 5) == []
    assert worker._crossing_events(above, 6) == []
    assert worker._crossing_events(below, 7) == []
    assert worker._crossing_events(below, 8)[0][1] == GateDirection.EXIT
    worker.set_gate_line(None)
    assert worker._crossing_events(above, 9) == []


def test_line_editor_syncs_running_worker(qapp, session_manager, seeded_users):
    widget = SourceManagementWidget(SourceService(session_manager), seeded_users["admin"])
    worker = VideoWorker(SourceConfig("cam", "Camera", SourceKind.LIVE, "0"))
    widget.worker = worker
    widget.canvas.line = GateLine()
    widget._line_drawn(widget.canvas.line)
    assert worker._line == widget.canvas.line
    widget._reverse_line(True)
    assert worker._line.entry_positive is False
    widget._clear_line()
    assert worker._line is None
    widget.worker = None
    widget.close()


def test_live_worker_emits_crossing_even_when_display_frames_are_replaced(qapp):
    worker = VideoWorker(
        SourceConfig("cam", "Camera", SourceKind.LIVE, "0", line=GateLine()),
        detector_factory=MovingVehicleDetector,
    )
    worker._detector = MovingVehicleDetector(None)
    worker._reset()
    candidates = []
    worker.event_candidate.connect(candidates.append)

    class LiveSequence(SequenceSource):
        def read(self):
            result = super().read()
            if result is None:
                worker.stop()
                return None
            index, _, image = result
            return index, None, image

    source = LiveSequence(None, None, None)
    worker._play(source)
    assert worker.frames_read == 6
    assert worker.dropped_frames == 5
    assert len(candidates) == 1
    assert candidates[0].source_kind == SourceKind.LIVE
    assert candidates[0].media_time_s is None
    assert candidates[0].direction == GateDirection.ENTRY
