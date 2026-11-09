"""Acceptance tests for Phase 1 (G1) user stories: NV-01, NV-03, NV-04, QT-01, M01, M05, M10."""

import os

# Ensure Qt runs offscreen during automated test suite
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PySide6.QtWidgets import QApplication

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.config.settings import seed_initial_accounts
from parking_app.domain.enums import UserRole, UserStatus, VehicleType
from parking_app.domain.exceptions import (
    AccountLockedError,
    DuplicatePlateError,
)
from parking_app.infrastructure.persistence.database import (
    DatabaseSessionManager,
    create_sqlite_engine,
)
from parking_app.ui.customer_view import CustomerManagementWidget, VehicleDialog
from parking_app.ui.main_window import MainWindow
from parking_app.ui.user_admin_view import CreateUserDialog


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def g1_env() -> dict:
    engine = create_sqlite_engine(":memory:")
    sm = DatabaseSessionManager(engine)
    sm.init_tables()
    seed_initial_accounts(sm)

    auth = AuthService(sm)
    cust = CustomerService(sm)
    audit = AuditService(sm)
    return {"sm": sm, "auth": auth, "cust": cust, "audit": audit}


@pytest.mark.parametrize("role", list(UserRole))
def test_create_user_dialog_saves_selected_role(
    qapp: QApplication, g1_env: dict, role: UserRole
) -> None:
    auth: AuthService = g1_env["auth"]
    admin = auth.authenticate("admin", "admin123")
    dialog = CreateUserDialog(auth, admin)
    dialog.username_input.setText("new_operator")
    dialog.name_input.setText("Người dùng thử")
    dialog.password_input.setText("password123")
    dialog.role_combo.setCurrentIndex(dialog.role_combo.findData(role))
    dialog.save_btn.click()

    assert dialog.result_user is not None, dialog.error_label.text()
    assert auth.authenticate("new_operator", "password123").role == role


def test_vehicle_dialog_registers_and_updates_vehicle(qapp: QApplication, g1_env: dict) -> None:
    service: CustomerService = g1_env["cust"]
    admin = g1_env["auth"].authenticate("admin", "admin123")
    customer = service.register_customer(admin, "KH_UI", "Khách thử", "0900000000")

    dialog = VehicleDialog(service, admin, customer.id)
    dialog.plate_input.setText("51A-123.45")
    dialog.type_combo.setCurrentIndex(1)
    dialog.save_btn.click()
    assert dialog.result_vehicle is not None, dialog.error_label.text()
    assert dialog.result_vehicle.vehicle_type == VehicleType.CAR
    assert service.find_by_plate("51A12345")[0] is not None

    edit = VehicleDialog(service, admin, customer.id, vehicle=dialog.result_vehicle)
    edit.type_combo.setCurrentIndex(0)
    edit.save_btn.click()
    assert edit.result_vehicle is not None, edit.error_label.text()
    assert service.find_by_plate("51A12345")[0].vehicle_type == VehicleType.MOTORCYCLE


def test_scenario_initial_account_seeding(g1_env: dict) -> None:
    """Verify default seeded accounts exist and can authenticate."""
    auth: AuthService = g1_env["auth"]

    admin = auth.authenticate("admin", "admin123")
    assert admin.role == UserRole.ADMIN
    assert admin.is_active is True

    manager = auth.authenticate("quanly", "quanly123")
    assert manager.role == UserRole.MANAGER

    staff = auth.authenticate("nhanvien", "nhanvien123")
    assert staff.role == UserRole.STAFF


def test_scenario_customer_and_multi_vehicle_workflow(g1_env: dict) -> None:
    """Full workflow: Staff logs in -> registers customer -> multi-vehicles -> duplicate check."""
    auth: AuthService = g1_env["auth"]
    cust: CustomerService = g1_env["cust"]

    staff = auth.authenticate("nhanvien", "nhanvien123")

    # 1. Register customer
    customer = cust.register_customer(
        actor=staff,
        customer_code="KH_VIP_01",
        full_name="Nguyễn Văn Đại Gia",
        phone_number="0988776655",
        note="Khách gửi xe dài hạn",
    )
    assert customer.id is not None

    # 2. Register first vehicle (Motorcycle) with presentation format
    v1 = cust.register_vehicle(
        actor=staff,
        customer_id=customer.id,
        raw_plate="59-P1 999.99",
        vehicle_type=VehicleType.MOTORCYCLE,
        note="SH 150i",
    )
    assert v1.normalized_plate == "59P199999"

    # 3. Register second vehicle (Car) for same customer (Multi-vehicle support)
    v2 = cust.register_vehicle(
        actor=staff,
        customer_id=customer.id,
        raw_plate="51K-888.88",
        vehicle_type=VehicleType.CAR,
        note="Mercedes GLC",
    )
    assert v2.normalized_plate == "51K88888"

    # Verify customer owns both vehicles
    customer_detail = cust.get_customer(customer.id)
    assert len(customer_detail.vehicles) == 2

    # 4. Attempt to register duplicate plate under another customer -> must fail
    another_cust = cust.register_customer(
        actor=staff,
        customer_code="KH_VIP_02",
        full_name="Trần Văn Hai",
        phone_number="0911223344",
    )
    with pytest.raises(DuplicatePlateError, match="59P199999"):
        cust.register_vehicle(
            actor=staff,
            customer_id=another_cust.id,
            raw_plate="59P1-999.99",  # Same plate, different presentation
            vehicle_type=VehicleType.MOTORCYCLE,
        )

    # 5. Lookup by plate (OCR search simulation)
    found_v, found_c = cust.find_by_plate("59p1 99999")
    assert found_v is not None
    assert found_v.normalized_plate == "59P199999"
    assert found_c.customer_code == "KH_VIP_01"


def test_scenario_admin_user_management_lifecycle(g1_env: dict) -> None:
    """Admin creates account, locks it, verifies block, unlocks, verifies success."""
    auth: AuthService = g1_env["auth"]
    admin = auth.authenticate("admin", "admin123")

    # Create new staff
    new_staff = auth.create_user(
        actor=admin,
        username="staff_cuong",
        plain_password="password_cuong_123",
        full_name="Nguyễn Văn Cường",
        role=UserRole.STAFF,
    )

    # New staff can log in
    logged_in = auth.authenticate("staff_cuong", "password_cuong_123")
    assert logged_in.id == new_staff.id

    # Admin locks account
    auth.set_user_status(admin, new_staff.id, UserStatus.LOCKED, reason="Tạm đình chỉ")

    # Staff is blocked
    with pytest.raises(AccountLockedError):
        auth.authenticate("staff_cuong", "password_cuong_123")

    # Admin unlocks account
    auth.set_user_status(admin, new_staff.id, UserStatus.ACTIVE, reason="Phục hồi")

    # Staff can log in again
    logged_in_again = auth.authenticate("staff_cuong", "password_cuong_123")
    assert logged_in_again.is_active is True


def test_ui_role_based_tabs_offscreen(qapp: QApplication, g1_env: dict) -> None:
    """Verify PySide6 MainWindow adapts tabs correctly based on role."""
    auth: AuthService = g1_env["auth"]
    cust: CustomerService = g1_env["cust"]
    audit: AuditService = g1_env["audit"]

    # 1. Staff: only 1 tab (Customer & Vehicle management)
    staff = auth.authenticate("nhanvien", "nhanvien123")
    w_staff = MainWindow(staff, auth, cust, audit)
    assert w_staff.tabs.count() == 1
    assert "Khách hàng" in w_staff.tabs.tabText(0)
    w_staff.close()

    # 2. Manager: 2 tabs (Customer & Vehicle + Audit log)
    manager = auth.authenticate("quanly", "quanly123")
    w_mgr = MainWindow(manager, auth, cust, audit)
    assert w_mgr.tabs.count() == 2
    w_mgr.close()

    # 3. Admin: 3 tabs (Customer & Vehicle + User Admin + Audit log)
    admin = auth.authenticate("admin", "admin123")
    w_admin = MainWindow(admin, auth, cust, audit)
    assert w_admin.tabs.count() == 3
    w_admin.close()


def test_ui_customer_management_widget_offscreen(qapp: QApplication, g1_env: dict) -> None:
    """Verify CustomerManagementWidget displays, searches, and selects customers."""
    auth: AuthService = g1_env["auth"]
    cust: CustomerService = g1_env["cust"]
    staff = auth.authenticate("nhanvien", "nhanvien123")

    # Seed a customer
    c = cust.register_customer(staff, "KH_UI_01", "Trần Thị Giao Diện", "0909090909")
    cust.register_vehicle(staff, c.id, "51H-111.11", VehicleType.MOTORCYCLE)

    widget = CustomerManagementWidget(cust, staff)
    assert widget.customer_table.rowCount() >= 1

    # Search for customer
    widget.search_input.setText("KH_UI_01")
    widget._on_search()
    assert widget.customer_table.rowCount() == 1

    # Select customer
    widget.customer_table.selectRow(0)
    assert widget.selected_customer is not None
    assert widget.selected_customer.customer_code == "KH_UI_01"
    assert widget.vehicle_table.rowCount() == 1
    assert widget.vehicle_table.item(0, 2).text() == "51H11111"
    widget.close()
