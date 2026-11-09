"""Integration tests for CustomerService (NV-03, NV-04, M05)."""

import pytest

from parking_app.application.customer_service import CustomerService
from parking_app.domain.enums import AuditAction, VehicleType
from parking_app.domain.exceptions import (
    DuplicateCustomerError,
    DuplicatePlateError,
    ValidationError,
)
from parking_app.domain.models import User
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository


def test_register_customer_successful(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    customer = service.register_customer(
        actor=staff,
        customer_code="KH0001",
        full_name="Nguyễn Văn An",
        phone_number="0912345678",
        note="Khách gửi xe tháng",
    )
    assert customer.id is not None
    assert customer.customer_code == "KH0001"
    assert customer.full_name == "Nguyễn Văn An"
    assert customer.phone_number == "0912345678"

    # Verify audit log
    with session_manager.session() as session:
        logs = SqlAlchemyAuditRepository(session).list_recent()
        cust_logs = [entry for entry in logs if entry.action == AuditAction.CREATE_CUSTOMER]
        assert len(cust_logs) == 1
        assert cust_logs[0].username == "staff_user"


def test_register_customer_missing_required_fields_fails(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    with pytest.raises(ValidationError, match="Mã khách hàng"):
        service.register_customer(staff, "", "Tên", "0900000000")

    with pytest.raises(ValidationError, match="Họ và tên"):
        service.register_customer(staff, "KH001", "", "0900000000")

    with pytest.raises(ValidationError, match="Số điện thoại"):
        service.register_customer(staff, "KH001", "Tên", "")


def test_register_customer_duplicate_code_fails(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    service.register_customer(staff, "KH_DUP", "Khách Một", "0911111111")
    with pytest.raises(DuplicateCustomerError, match="đã tồn tại"):
        service.register_customer(staff, "KH_DUP", "Khách Hai", "0922222222")


def test_one_customer_can_register_multiple_vehicles(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    """NV-04: Một khách hàng có thể liên kết với nhiều phương tiện."""
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    customer = service.register_customer(staff, "KH_MULTI", "Lê Văn Đa Xe", "0933333333")

    # Register first vehicle: Motorcycle
    veh1 = service.register_vehicle(
        actor=staff,
        customer_id=customer.id,
        raw_plate="59-P1 123.45",
        vehicle_type=VehicleType.MOTORCYCLE,
        note="Xe máy Honda SH",
    )
    assert veh1.normalized_plate == "59P112345"
    assert veh1.vehicle_type == VehicleType.MOTORCYCLE

    # Register second vehicle: Car
    veh2 = service.register_vehicle(
        actor=staff,
        customer_id=customer.id,
        raw_plate="51A-888.88",
        vehicle_type=VehicleType.CAR,
        note="Ô tô Toyota Camry",
    )
    assert veh2.normalized_plate == "51A88888"
    assert veh2.vehicle_type == VehicleType.CAR

    # Retrieve customer with vehicles loaded
    fetched = service.get_customer(customer.id)
    assert fetched is not None
    assert len(fetched.vehicles) == 2
    plates = {v.normalized_plate for v in fetched.vehicles}
    assert plates == {"59P112345", "51A88888"}


def test_duplicate_plate_fails_across_customers(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    """NV-04: Biển đã thuộc hồ sơ khác tạo cảnh báo/lỗi."""
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    cust1 = service.register_customer(staff, "KH_A", "Chủ Xe 1", "0944444441")
    cust2 = service.register_customer(staff, "KH_B", "Chủ Xe 2", "0944444442")

    # Cust1 registers plate 72-G1 456.78
    service.register_vehicle(staff, cust1.id, "72-G1 456.78", VehicleType.MOTORCYCLE)

    # Cust2 tries to register same plate with different formatting 72g145678
    with pytest.raises(DuplicatePlateError, match="đã được đăng ký trong hệ thống"):
        service.register_vehicle(staff, cust2.id, "72G1-45678", VehicleType.MOTORCYCLE)


def test_find_by_plate(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    customer = service.register_customer(staff, "KH_FIND", "Phan Văn Tìm", "0988888888")
    service.register_vehicle(staff, customer.id, "43-B1 777.77", VehicleType.MOTORCYCLE)

    # Search with messy presentation string
    veh, owner = service.find_by_plate("  43b1.777-77 ")
    assert veh is not None
    assert veh.normalized_plate == "43B177777"
    assert owner is not None
    assert owner.customer_code == "KH_FIND"
    assert owner.full_name == "Phan Văn Tìm"

    # Search non-existent plate
    v_none, o_none = service.find_by_plate("99Z99999")
    assert v_none is None
    assert o_none is None


def test_delete_vehicle(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = CustomerService(session_manager)
    staff = seeded_users["staff"]

    customer = service.register_customer(staff, "KH_DEL", "Trần Xóa Xe", "0977777777")
    veh = service.register_vehicle(staff, customer.id, "60-A 111.11", VehicleType.CAR)

    # Delete vehicle
    assert service.delete_vehicle(staff, veh.id, reason="Khách bán xe") is True

    # Plate is now free and can be registered again
    cust2 = service.register_customer(staff, "KH_NEW_OWNER", "Chủ Mới", "0966666666")
    new_veh = service.register_vehicle(staff, cust2.id, "60A11111", VehicleType.CAR)
    assert new_veh.id is not None
