"""Acceptance tests for Phase 2 operator-confirmed parking workflows."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import ParkingStatus, VehicleType
from parking_app.domain.models import User
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.ui.main_window import MainWindow
from parking_app.ui.parking_view import ParkingManagementWidget


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_operator_confirms_entry_exit_and_looks_up_history(
    qapp: QApplication,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staff = seeded_users["staff"]
    storage = EvidenceStorage(tmp_path / "evidence")
    service = ParkingService(session_manager, storage, motorcycle_capacity=4, car_capacity=2)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text, *args: messages.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, text, *args: messages.append((title, text)),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget = ParkingManagementWidget(service, staff)

    entry_image = tmp_path / "entry.jpg"
    entry_image.write_bytes(
        storage.create_synthetic_image("51A-123.45", VehicleType.MOTORCYCLE, is_entry=True)
    )
    exit_image = tmp_path / "exit.jpg"
    exit_image.write_bytes(
        storage.create_synthetic_image("51A-123.45", VehicleType.MOTORCYCLE, is_entry=False)
    )
    widget.entry_plate_input.setText("51A-123.45")
    widget.entry_image_path = str(entry_image)
    widget._create_entry()
    assert widget.active_table.rowCount() == 1, messages
    session_code = widget.active_table.item(0, 0).text()

    widget.active_table.selectRow(0)
    assert widget.selected_session_id is not None
    widget.exit_image_path = str(exit_image)
    widget._close_exit()

    sessions = service.search_sessions(plate_query=session_code)
    assert len(sessions) == 1
    assert sessions[0].status == ParkingStatus.DA_RA
    assert sessions[0].entry_image_path is not None
    assert sessions[0].exit_image_path is not None
    assert widget.active_table.rowCount() == 0

    widget.history_query_input.setText("51A-123.45")
    widget._search_history()
    assert widget.history_table.rowCount() == 1
    assert widget.history_table.item(0, 5).text() == ParkingStatus.DA_RA.display_name
    widget.history_table.selectRow(0)
    assert not widget.history_entry_preview.pixmap().isNull()
    assert not widget.history_exit_preview.pixmap().isNull()
    assert messages == []
    widget.close()

    main_window = MainWindow(
        current_user=staff,
        auth_service=AuthService(session_manager),
        customer_service=CustomerService(session_manager),
        audit_service=AuditService(session_manager),
        parking_service=service,
    )
    assert main_window.tabs.tabText(0) == "Vận hành bãi xe"
    assert main_window.tabs.count() == 2
    main_window.close()


def test_entry_warns_on_registered_vehicle_type_mismatch(
    qapp: QApplication,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staff = seeded_users["staff"]
    customer_service = CustomerService(session_manager)
    customer = customer_service.register_customer(
        staff,
        "KH_G2_MISMATCH",
        "Khách Kiểm Thử",
        "0900111222",
    )
    customer_service.register_vehicle(
        staff,
        customer.id,
        "51A-654.32",
        VehicleType.CAR,
    )
    storage = EvidenceStorage(tmp_path / "evidence")
    service = ParkingService(session_manager, storage, motorcycle_capacity=4, car_capacity=2)
    image_path = tmp_path / "entry.jpg"
    image_path.write_bytes(
        storage.create_synthetic_image("51A-654.32", VehicleType.MOTORCYCLE, is_entry=True)
    )
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, text, *args: messages.append((title, text)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, text, *args: messages.append((title, text)),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget = ParkingManagementWidget(service, staff)
    widget.entry_plate_input.setText("51A-654.32")
    widget.entry_type_combo.setCurrentIndex(0)
    assert "hồ sơ đăng ký là Ô tô" in widget.entry_type_warning.text()
    widget.entry_attention_check.setChecked(True)
    widget.entry_image_path = str(image_path)

    widget._create_entry()
    entries = service.search_sessions(plate_query="51A-654.32")

    assert len(entries) == 1
    assert entries[0].needs_attention is True
    assert entries[0].attention_reason is not None
    assert messages == []
    widget.close()
