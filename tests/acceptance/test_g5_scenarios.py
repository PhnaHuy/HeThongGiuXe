import os
import time
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.plate_recognition import PlateRecognitionService
from parking_app.application.source_service import SourceService
from parking_app.domain.enums import AuditAction, ParkingStatus, VehicleType
from parking_app.domain.plate import (
    PlateOCRObservation,
    PlateRecognition,
    PlateRecognitionOptions,
)
from parking_app.domain.video import SourceKind
from parking_app.domain.vision import EventCandidate, GateDirection
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.ui.main_window import MainWindow
from parking_app.ui.parking_view import ParkingManagementWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait_until(qapp, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert predicate(), "Timed out waiting for G5 OCR result"


def plate_image():
    image = np.full((220, 360, 3), (110, 150, 195), dtype=np.uint8)
    cv2.rectangle(image, (80, 120), (280, 180), (255, 255, 255), -1)
    cv2.rectangle(image, (80, 120), (280, 180), (0, 0, 0), 3)
    cv2.putText(
        image,
        "51A12345",
        (92, 162),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def event_candidate(direction, image_data, vehicle_type=VehicleType.CAR):
    return EventCandidate(
        id=f"event-{direction.value.lower()}",
        source_id="gate-1",
        source_name="Cổng chính",
        source_kind=SourceKind.LIVE,
        stream_id="stream-1",
        track_id=12,
        direction=direction,
        vehicle_type=vehicle_type,
        confidence=0.93,
        observed_at=datetime.now(UTC),
        media_time_s=None,
        image_data=image_data,
        vehicle_image_samples=(image_data, image_data),
    )


class FixedOCR:
    def recognize(self, crops):
        return tuple(("51A-12345", 0.96) for _ in crops)


def fake_recognition_service(tmp_path):
    options = PlateRecognitionOptions(
        python_path=tmp_path / "unused-python.exe",
        worker_path=tmp_path / "unused-worker.py",
        cache_dir=tmp_path / "unused-cache",
    )
    return PlateRecognitionService(options, ocr_client=FixedOCR())


def recognition(image_data):
    return PlateRecognition(
        observations=(
            PlateOCRObservation(
                raw_text="51A-12345",
                confidence=0.96,
                normalized_plate="51A12345",
            ),
        ),
        proposed_plate="51A12345",
        confidence=0.96,
        plate_image_data=image_data,
        samples_considered=2,
    )


def test_entry_ocr_is_only_a_suggestion_and_is_audited_with_plate_crop(
    qapp,
    session_manager,
    seeded_users,
    tmp_path,
    monkeypatch,
):
    storage = EvidenceStorage(tmp_path / "evidence")
    parking = ParkingService(session_manager, storage)
    window = MainWindow(
        seeded_users["staff"],
        AuthService(session_manager),
        CustomerService(session_manager),
        AuditService(session_manager),
        parking_service=parking,
        source_service=SourceService(session_manager),
        plate_recognition_service=fake_recognition_service(tmp_path),
    )
    image_data = plate_image()
    window._review_candidate(event_candidate(GateDirection.ENTRY, image_data))

    wait_until(
        qapp,
        lambda: window.parking_widget.entry_plate_input.text() == "51A12345",
    )
    assert parking.list_active_sessions() == []
    assert window.parking_widget.entry_plate_status.text().startswith("OCR đề xuất")
    window.parking_widget.entry_plate_input.setText("51A12346")
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: QMessageBox.StandardButton.Ok,
    )

    window.parking_widget._create_entry()
    active = parking.list_active_sessions()
    assert len(active) == 1
    assert active[0].snapshot_plate == "51A12346"

    audits = AuditService(session_manager).list_recent_audits(seeded_users["manager"])
    entry_audit = next(audit for audit in audits if audit.action == AuditAction.CONFIRM_ENTRY)
    plate_ocr = entry_audit.new_values["plate_ocr"]
    assert plate_ocr["raw_text"] == "51A-12345 | 51A-12345"
    assert plate_ocr["proposed_plate"] == "51A12345"
    assert plate_ocr["confirmed_plate"] == "51A12346"
    assert entry_audit.new_values["plate_correction"] == {
        "before": "51A12345",
        "after": "51A12346",
    }
    assert Path(plate_ocr["plate_image_path"]).is_file()
    window.close()


def test_exit_ocr_filters_without_selecting_or_closing_a_session(
    qapp,
    session_manager,
    seeded_users,
    tmp_path,
    monkeypatch,
):
    storage = EvidenceStorage(tmp_path / "evidence")
    parking = ParkingService(session_manager, storage)
    stay = parking.create_entry(seeded_users["staff"], "51A12345", VehicleType.CAR)
    widget = ParkingManagementWidget(parking, seeded_users["staff"])
    image_data = plate_image()
    exit_candidate = event_candidate(
        GateDirection.EXIT,
        image_data,
        vehicle_type=VehicleType.MOTORCYCLE,
    )
    widget.stage_event_candidate(exit_candidate)
    widget.stage_plate_recognition(exit_candidate.id, recognition(image_data))

    assert widget.active_table.rowCount() == 1
    assert widget.selected_session_id is None
    assert parking.get_session(stay.id).status == ParkingStatus.DANG_GUI

    widget.active_table.selectRow(0)
    assert widget.selected_session_id == stay.id
    assert "Cảnh báo" in widget.exit_plate_status.text()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: QMessageBox.StandardButton.Ok,
    )
    widget._close_exit()

    assert parking.get_session(stay.id).status == ParkingStatus.DA_RA
    audits = AuditService(session_manager).list_recent_audits(seeded_users["manager"])
    exit_audit = next(audit for audit in audits if audit.action == AuditAction.CONFIRM_EXIT)
    plate_ocr = exit_audit.new_values["plate_ocr"]
    assert plate_ocr["raw_text"] == "51A-12345"
    assert plate_ocr["matched_session_plate"] == "51A12345"
    assert exit_audit.new_values["vehicle_type_review"]["mismatch"]
    assert Path(plate_ocr["plate_image_path"]).is_file()
    widget.close()
