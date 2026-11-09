"""G6 role-based management screens and operator safety checks."""

import os
import threading
import time
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import VehicleType
from parking_app.domain.models import User
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.ui.dashboard_view import ParkingDashboardWidget
from parking_app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def build_window(session_manager, parking, user):
    return MainWindow(
        user,
        AuthService(session_manager),
        CustomerService(session_manager),
        AuditService(session_manager),
        parking_service=parking,
    )


def wait_for_dashboard_refresh(app, dashboard) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if dashboard._refresh_worker is None and not dashboard._refresh_pending:
            time.sleep(0.01)
            app.processEvents()
            if dashboard._refresh_worker is None and not dashboard._refresh_pending:
                return
        time.sleep(0.01)
    raise AssertionError("Dashboard refresh did not complete")


def test_g6_tabs_are_available_only_to_authorized_roles(
    qapp,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    tmp_path,
) -> None:
    parking = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    staff_window = build_window(session_manager, parking, seeded_users["staff"])
    manager_window = build_window(session_manager, parking, seeded_users["manager"])
    admin_window = build_window(session_manager, parking, seeded_users["admin"])

    staff_tabs = [staff_window.tabs.tabText(i) for i in range(staff_window.tabs.count())]
    manager_tabs = [manager_window.tabs.tabText(i) for i in range(manager_window.tabs.count())]
    admin_tabs = [admin_window.tabs.tabText(i) for i in range(admin_window.tabs.count())]
    assert "Tổng quan và thống kê" not in staff_tabs
    assert "Theo dõi bất thường" not in staff_tabs
    assert "Tổng quan và thống kê" in manager_tabs
    assert "Theo dõi bất thường" in manager_tabs
    assert "Cấu hình sức chứa" not in manager_tabs
    assert "Cấu hình sức chứa" in admin_tabs
    assert "Quản lý Tài khoản (Admin)" in admin_tabs

    wait_for_dashboard_refresh(qapp, manager_window.dashboard_widget)
    wait_for_dashboard_refresh(qapp, admin_window.dashboard_widget)
    staff_window.close()
    manager_window.close()
    admin_window.close()


def test_g6_manager_dashboard_refreshes_after_confirmed_entry(
    qapp,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    tmp_path,
) -> None:
    parking = ParkingService(
        session_manager,
        EvidenceStorage(tmp_path / "evidence"),
        motorcycle_capacity=5,
        car_capacity=2,
    )
    window = build_window(session_manager, parking, seeded_users["manager"])
    dashboard = window.dashboard_widget
    before = dashboard.total_occupancy.text()
    parking.create_entry(seeded_users["staff"], "51A12345", VehicleType.MOTORCYCLE)
    window.parking_widget.session_state_changed.emit()
    wait_for_dashboard_refresh(qapp, dashboard)
    assert dashboard.total_occupancy.text() != before
    assert "1 / 5" in dashboard.motorcycle_occupancy.text()
    window.close()


def test_dashboard_date_filter_counts_confirmed_entry_and_exit(
    qapp, session_manager: DatabaseSessionManager, seeded_users: dict[str, User], tmp_path
) -> None:
    parking = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    window = build_window(session_manager, parking, seeded_users["manager"])
    dashboard = window.dashboard_widget
    car = parking.create_entry(seeded_users["staff"], "51A12345", VehicleType.CAR)
    parking.close_exit(seeded_users["staff"], car.id)
    today = datetime.now().astimezone().date()
    dashboard.from_date.setText((today - timedelta(days=1)).isoformat())
    dashboard.to_date.setText(today.isoformat())
    dashboard.apply_button.click()
    wait_for_dashboard_refresh(qapp, dashboard)
    assert "Tổng: 1 lượt vào, 1 lượt ra" in dashboard.statistics.text()
    dashboard.to_date.setText((today - timedelta(days=1)).isoformat())
    dashboard.apply_button.click()
    wait_for_dashboard_refresh(qapp, dashboard)
    assert "Tổng: 0 lượt vào, 0 lượt ra" in dashboard.statistics.text()
    window.close()


def test_window_close_waits_for_dashboard_operation(
    qapp,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    tmp_path,
    monkeypatch,
) -> None:
    parking = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    operation_started = threading.Event()
    release_operation = threading.Event()
    refresh_errors = []
    original_statistics = parking.get_statistics

    def record_refresh_error(_dashboard, message):
        refresh_errors.append(message)

    def delayed_statistics(actor, start, before):
        operation_started.set()
        if not release_operation.wait(5):
            raise TimeoutError("Test operation was not released.")
        return original_statistics(actor, start, before)

    monkeypatch.setattr(parking, "get_statistics", delayed_statistics)
    monkeypatch.setattr(ParkingDashboardWidget, "_refresh_failed", record_refresh_error)
    window = build_window(session_manager, parking, seeded_users["manager"])
    dashboard = window.dashboard_widget
    window.show()
    assert operation_started.wait(5)
    assert not window.close()
    assert window.isVisible()

    release_operation.set()
    wait_for_dashboard_refresh(qapp, dashboard)
    assert refresh_errors == []
    assert not window.isVisible()
