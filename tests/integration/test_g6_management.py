"""G6 management workflows: capacity, statistics, profiles and exceptions."""

from datetime import UTC, datetime, timedelta

import pytest

from parking_app.application.audit_service import AuditService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import AuditAction, ParkingStatus, VehicleType
from parking_app.domain.exceptions import PermissionDeniedError, ValidationError
from parking_app.domain.models import User
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository


@pytest.fixture
def parking_service(
    session_manager: DatabaseSessionManager,
    tmp_path,
) -> ParkingService:
    return ParkingService(
        session_manager,
        EvidenceStorage(tmp_path / "evidence"),
        motorcycle_capacity=3,
        car_capacity=2,
    )


@pytest.fixture
def evidence_storage(tmp_path) -> EvidenceStorage:
    return EvidenceStorage(tmp_path / "evidence")


def test_capacity_is_admin_only_audited_and_persistent(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
    evidence_storage: EvidenceStorage,
) -> None:
    with pytest.raises(PermissionDeniedError):
        parking_service.update_capacity(seeded_users["manager"], 8, 4)
    with pytest.raises(ValidationError):
        parking_service.update_capacity(seeded_users["admin"], -1, 4)

    parking_service.update_capacity(seeded_users["admin"], 8, 4)
    reloaded = ParkingService(session_manager, evidence_storage, 99, 99)
    summary = reloaded.get_capacity_summary()
    assert (summary.motorcycle_capacity, summary.car_capacity) == (8, 4)

    with session_manager.session() as session:
        audit = SqlAlchemyAuditRepository(session).list_recent(
            action=AuditAction.CONFIGURE_CAPACITY
        )[0]
    assert audit.old_values == {"motorcycle": 3, "car": 2}
    assert audit.new_values == {"motorcycle": 8, "car": 4}


def test_statistics_count_entries_and_exits_in_selected_period(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    start = datetime.now(UTC) - timedelta(minutes=1)
    car = parking_service.create_entry(staff, "51A12345", VehicleType.CAR)
    parking_service.create_entry(staff, "59B12345", VehicleType.MOTORCYCLE)
    parking_service.close_exit(staff, car.id)

    statistics = parking_service.get_statistics(
        seeded_users["manager"],
        start,
        datetime.now(UTC) + timedelta(minutes=1),
    )
    assert statistics.total_entries == 2
    assert statistics.total_exits == 1
    assert statistics.motorcycle_entries == 1
    assert statistics.motorcycle_exits == 0
    assert statistics.car_entries == statistics.car_exits == 1
    assert parking_service.get_session(car.id).status == ParkingStatus.DA_RA

    with pytest.raises(PermissionDeniedError):
        parking_service.get_statistics(staff)


def test_manager_can_resolve_unmatched_exit_and_flagged_session(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    manager = seeded_users["manager"]
    audit_service = AuditService(session_manager)
    incident_id = parking_service.record_unmatched_exit(
        staff,
        reason="Không tìm thấy lượt sau khi rà soát.",
        plate_query="51A12345",
    )

    pending = audit_service.list_exceptions(manager, handled=False)
    incident = next(case for case in pending if case.reference == incident_id)
    assert incident.category == "Không tìm thấy lượt xe ra"
    audit_service.resolve_exception(manager, incident_id, "Đã đối chiếu camera và ghi nhận.")
    assert not any(
        case.reference == incident_id for case in audit_service.list_exceptions(manager, False)
    )
    assert any(
        case.reference == incident_id for case in audit_service.list_exceptions(manager, True)
    )

    session = parking_service.create_entry(staff, "61C12345", VehicleType.MOTORCYCLE)
    parking_service.flag_session_attention(staff, session.id, "Cần đối chiếu hồ sơ.")
    unresolved = next(
        case
        for case in audit_service.list_exceptions(manager, handled=False)
        if case.session_code == session.session_code
    )
    assert unresolved.description == "Cần đối chiếu hồ sơ."
    parking_service.resolve_session_attention(
        manager,
        session.session_code,
        "Đã kiểm tra hồ sơ và ảnh.",
    )
    assert not any(
        case.session_code == session.session_code
        for case in audit_service.list_exceptions(manager, handled=False)
    )
    assert any(
        case.session_code == session.session_code
        for case in audit_service.list_exceptions(manager, handled=True)
    )


def test_customer_search_by_plate_and_admin_vehicle_correction_is_audited(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
    parking_service: ParkingService,
) -> None:
    customers = CustomerService(session_manager)
    staff = seeded_users["staff"]
    customer = customers.register_customer(staff, "KH-G6", "Nguyễn An", "0900000000")
    vehicle = customers.register_vehicle(
        staff,
        customer.id,
        "51A-123.45",
        VehicleType.MOTORCYCLE,
    )
    active_session = parking_service.create_entry(
        staff,
        vehicle.display_plate,
        vehicle.vehicle_type,
    )
    assert customers.search_customers("51A12345")[0].id == customer.id
    assert customers.search_customers("51A-123.45")[0].id == customer.id

    with pytest.raises(PermissionDeniedError):
        customers.update_vehicle(
            seeded_users["manager"],
            vehicle.id,
            "51A-543.21",
            VehicleType.MOTORCYCLE,
        )
    updated = customers.update_vehicle(
        seeded_users["admin"],
        vehicle.id,
        "51A-543.21",
        VehicleType.CAR,
    )
    assert updated.normalized_plate == "51A54321"
    snapshot = parking_service.get_session(active_session.id)
    assert snapshot.snapshot_plate == "51A12345"
    assert snapshot.snapshot_vehicle_type == VehicleType.MOTORCYCLE
    assert customers.search_customers("51A54321")[0].id == customer.id
    with session_manager.session() as session:
        audit = SqlAlchemyAuditRepository(session).list_recent(action=AuditAction.UPDATE_VEHICLE)[0]
    assert audit.old_values["normalized_plate"] == "51A12345"
    assert audit.new_values["normalized_plate"] == "51A54321"


def test_confirmed_ocr_correction_is_visible_as_a_handled_exception(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    parking_service.create_entry(
        actor=seeded_users["staff"],
        raw_plate="51A12346",
        vehicle_type=VehicleType.CAR,
        ocr_raw_text="51A12345",
        ocr_proposed_plate="51A12345",
    )
    cases = AuditService(session_manager).list_exceptions(
        seeded_users["manager"],
        handled=True,
    )
    correction = next(case for case in cases if case.plate == "51A12346")
    assert correction.category == "Biển số OCR khác kết quả đối chiếu"
    assert correction.operator == seeded_users["staff"].username
