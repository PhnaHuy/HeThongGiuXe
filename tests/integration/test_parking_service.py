"""Integration tests for ParkingService (M06, M07, M08, M10, NV-05, NV-06, NV-07, NV-08, NV-12)."""

from datetime import UTC, timedelta
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import (
    AuditAction,
    ParkingStatus,
    VehicleType,
)
from parking_app.domain.exceptions import (
    DuplicateActiveSessionError,
    PermissionDeniedError,
    SessionAlreadyClosedError,
)
from parking_app.domain.models import ParkingSession, User
from parking_app.domain.video import SourceKind
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemySessionRepository,
)


@pytest.fixture
def evidence_storage(tmp_path) -> EvidenceStorage:
    return EvidenceStorage(tmp_path / "evidence")


@pytest.fixture
def parking_service(
    session_manager: DatabaseSessionManager, evidence_storage: EvidenceStorage
) -> ParkingService:
    return ParkingService(
        session_manager=session_manager,
        evidence_storage=evidence_storage,
        motorcycle_capacity=3,  # Small capacity for easy testing
        car_capacity=2,
    )


def test_create_entry_registered_vehicle(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    evidence_storage: EvidenceStorage,
    seeded_users: dict[str, User],
) -> None:
    """NV-05: Xe vào tạo đúng một lượt đang mở, có giờ vào và ảnh."""
    staff = seeded_users["staff"]
    cust_service = CustomerService(session_manager)

    # Pre-register customer and motorcycle
    cust = cust_service.register_customer(staff, "KH_01", "Trần Đăng Ký", "0912345678")
    veh = cust_service.register_vehicle(staff, cust.id, "51F-123.45", VehicleType.MOTORCYCLE)

    img_data = evidence_storage.create_synthetic_image("51F-123.45", VehicleType.MOTORCYCLE, True)

    session = parking_service.create_entry(
        actor=staff,
        raw_plate="51F-123.45",
        vehicle_type=VehicleType.MOTORCYCLE,
        image_data=img_data,
        note="Xe vào bình thường",
    )

    assert session.id is not None
    assert session.snapshot_plate == "51F12345"
    assert session.snapshot_vehicle_type == VehicleType.MOTORCYCLE
    assert session.is_registered_customer is True
    assert session.customer_id == cust.id
    assert session.vehicle_id == veh.id
    assert session.status == ParkingStatus.DANG_GUI
    assert session.entry_image_path is not None

    # Check capacity updated
    summary = parking_service.get_capacity_summary()
    assert summary.motorcycle_active == 1
    assert summary.motorcycle_remaining == 2


def test_create_entry_unregistered_guest(
    parking_service: ParkingService,
    evidence_storage: EvidenceStorage,
    seeded_users: dict[str, User],
) -> None:
    """NV-06: Tiếp nhận khách vãng lai, vẫn có mã lượt, loại xe, giờ vào và ảnh."""
    staff = seeded_users["staff"]
    img_data = evidence_storage.create_synthetic_image("29A-888.88", VehicleType.CAR, True)

    session = parking_service.create_entry(
        actor=staff,
        raw_plate="29A-888.88",
        vehicle_type=VehicleType.CAR,
        image_data=img_data,
        note="Khách vãng lai gửi theo giờ",
    )

    assert session.is_registered_customer is False
    assert session.customer_id is None
    assert session.snapshot_plate == "29A88888"
    assert session.status == ParkingStatus.DANG_GUI


def test_create_entry_unreadable_plate(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """NV-06 / NV-09: Xe không đọc được biển vẫn có mã lượt riêng để đối chiếu thủ công."""
    staff = seeded_users["staff"]
    session = parking_service.create_entry(
        actor=staff,
        raw_plate="",
        vehicle_type=VehicleType.MOTORCYCLE,
        note="Biển số mờ bùn đất",
    )
    assert session.id is not None
    assert session.snapshot_plate.startswith("UNREADABLE_")
    assert session.snapshot_display_plate == "CHƯA ĐỌC ĐƯỢC BIỂN"
    assert session.status == ParkingStatus.DANG_GUI


def test_duplicate_open_session_rejected(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """Bất biến: Không tạo hai lượt đang mở cho cùng một biển số."""
    staff = seeded_users["staff"]
    parking_service.create_entry(staff, "59-P1 999.99", VehicleType.MOTORCYCLE)

    # Attempt to create duplicate open session with different presentation format
    with pytest.raises(DuplicateActiveSessionError, match="59P199999"):
        parking_service.create_entry(staff, "59P1-999.99", VehicleType.MOTORCYCLE)


def test_close_exit_successful(
    parking_service: ParkingService,
    evidence_storage: EvidenceStorage,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    """NV-07: Sau xác nhận, lưu giờ/ảnh lúc ra, đóng lượt và cập nhật số xe trong bãi."""
    staff = seeded_users["staff"]
    entry_img = evidence_storage.create_synthetic_image("43B1-1234", VehicleType.MOTORCYCLE, True)
    session = parking_service.create_entry(
        staff, "43-B1 1234", VehicleType.MOTORCYCLE, image_data=entry_img
    )

    exit_img = evidence_storage.create_synthetic_image("43B1-1234", VehicleType.MOTORCYCLE, False)
    closed = parking_service.close_exit(
        actor=staff,
        session_id_or_code=session.id,
        image_data=exit_img,
        note="Đã đối chiếu khớp ảnh vào/ra",
    )

    assert closed.status == ParkingStatus.DA_RA
    assert closed.exit_time is not None
    assert closed.exit_image_path is not None
    assert closed.exit_operator_id == staff.id

    # Capacity freed up
    summary = parking_service.get_capacity_summary()
    assert summary.motorcycle_active == 0


def test_cannot_close_session_twice(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """Bất biến: Một lượt đã DA_RA không thể đóng lần thứ hai."""
    staff = seeded_users["staff"]
    session = parking_service.create_entry(staff, "72G1-555.55", VehicleType.MOTORCYCLE)
    parking_service.close_exit(staff, session.id)

    # Second close attempt must be rejected
    with pytest.raises(SessionAlreadyClosedError, match="đã được đóng trước đó"):
        parking_service.close_exit(staff, session.id)


def test_update_session_snapshot_preserves_vehicle_registry(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """NV-08: Sửa thông tin trên lượt lưu trước/sau, không sửa ngược vào hồ sơ xe."""
    staff = seeded_users["staff"]
    cust_service = CustomerService(session_manager)

    cust = cust_service.register_customer(staff, "KH_SNAP", "Bảo Vệ Snapshot", "0900000001")
    cust_service.register_vehicle(staff, cust.id, "51A-111.11", VehicleType.CAR)

    session = parking_service.create_entry(staff, "51A-111.11", VehicleType.CAR)

    # Staff corrects OCR error on session: 51A11111 -> 51A11112
    updated = parking_service.update_session_snapshot(
        actor=staff,
        session_id=session.id,
        new_plate="51A-111.12",
        reason="Biển số mờ nhìn nhầm số 1 thành 2",
    )
    assert updated.snapshot_plate == "51A11112"

    # Vehicle in customer registry must still be 51A11111 (Invariant preserved!)
    stored_veh = cust_service.find_by_plate("51A11111")[0]
    assert stored_veh is not None
    assert stored_veh.normalized_plate == "51A11111"


def test_flag_session_does_not_close_it(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """NV-09 / NV-10: Cờ CAN_XU_LY không tự đóng lượt."""
    staff = seeded_users["staff"]
    session = parking_service.create_entry(staff, "60B-777.77", VehicleType.MOTORCYCLE)

    flagged = parking_service.flag_session_attention(
        actor=staff,
        session_id=session.id,
        reason="Loại xe lúc vào không khớp",
    )
    assert flagged.needs_attention is True
    assert flagged.status == ParkingStatus.DANG_GUI  # NOT closed!


def test_full_capacity_warns_without_blocking_entry(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    """NV-12: Sức chứa đầy là cảnh báo, không tự động từ chối xe."""
    staff = seeded_users["staff"]

    # Fill the configured motorcycle capacity.
    parking_service.create_entry(staff, "51A-000.01", VehicleType.MOTORCYCLE)
    parking_service.create_entry(staff, "51A-000.02", VehicleType.MOTORCYCLE)
    parking_service.create_entry(staff, "51A-000.03", VehicleType.MOTORCYCLE)

    overflow = parking_service.create_entry(staff, "51A-000.04", VehicleType.MOTORCYCLE)
    summary = parking_service.get_capacity_summary()

    assert overflow.status == ParkingStatus.DANG_GUI
    assert summary.motorcycle_active == 4
    assert summary.motorcycle_remaining == 0
    assert summary.is_motorcycle_full is True
    assert summary.is_full is False


def test_search_sessions_by_customer_and_entry_time(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    customer_service = CustomerService(session_manager)
    customer = customer_service.register_customer(
        staff,
        "KH_TIM_KIEM",
        "Nguyễn Tìm Kiếm",
        "0900123456",
    )
    vehicle = customer_service.register_vehicle(
        staff,
        customer.id,
        "51A-777.77",
        VehicleType.CAR,
    )
    entry = parking_service.create_entry(staff, vehicle.display_plate, VehicleType.CAR)
    entry_time = entry.entry_time
    if entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=UTC)

    results = parking_service.search_sessions(
        customer_query="NGUYỄN TÌM",
        status=ParkingStatus.DANG_GUI,
        vehicle_type=VehicleType.CAR,
        entry_from=entry_time - timedelta(seconds=1),
        entry_before=entry_time + timedelta(seconds=1),
    )

    assert [item.session_code for item in results] == [entry.session_code]


def test_mismatched_registered_vehicle_type_can_be_flagged_and_audited(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    customer_service = CustomerService(session_manager)
    customer = customer_service.register_customer(staff, "KH_LOAI_XE", "Khách Mẫu", "0900999888")
    customer_service.register_vehicle(
        staff,
        customer.id,
        "51A-888.88",
        VehicleType.CAR,
    )

    entry = parking_service.create_entry(
        staff,
        "51A-888.88",
        VehicleType.MOTORCYCLE,
        attention_reason="Loại xe đã đăng ký không khớp loại nhân viên xác nhận.",
    )

    with session_manager.session() as session:
        audit = next(
            item
            for item in SqlAlchemyAuditRepository(session).list_recent(user_id=staff.id)
            if item.action == AuditAction.CONFIRM_ENTRY
        )

    assert entry.needs_attention is True
    assert audit.action == AuditAction.CONFIRM_ENTRY
    assert audit.new_values["registered_vehicle_type"] == VehicleType.CAR.value
    assert audit.new_values["type"] == VehicleType.MOTORCYCLE.value
    assert audit.new_values["attention_reason"] == entry.attention_reason


def test_unmatched_exit_is_recorded_with_operator_and_image(
    parking_service: ParkingService,
    evidence_storage: EvidenceStorage,
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    image = evidence_storage.create_synthetic_image("51A-999.99", VehicleType.CAR, is_entry=False)

    incident_code = parking_service.record_unmatched_exit(
        actor=staff,
        reason="Không tìm thấy lượt phù hợp sau khi kiểm tra biển số.",
        plate_query="51A-999.99",
        vehicle_type=VehicleType.CAR,
        image_data=image,
    )

    with session_manager.session() as session:
        audit = SqlAlchemyAuditRepository(session).list_recent(user_id=staff.id)[0]

    assert audit.action == AuditAction.RECORD_EXCEPTION
    assert audit.target_type == "UNMATCHED_EXIT"
    assert audit.target_id == incident_code
    assert audit.new_values["plate_query"] == "51A-999.99"
    assert Path(audit.new_values["evidence_path"]).is_file()


def test_locked_operator_cannot_confirm_entry(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    with pytest.raises(PermissionDeniedError, match="không hoạt động"):
        parking_service.create_entry(
            seeded_users["locked"],
            "51A-999.99",
            VehicleType.MOTORCYCLE,
        )


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_non_staff_cannot_confirm_entry(
    parking_service: ParkingService,
    seeded_users: dict[str, User],
    role: str,
) -> None:
    with pytest.raises(PermissionDeniedError, match="Chỉ nhân viên"):
        parking_service.create_entry(
            seeded_users[role],
            "51A-999.98",
            VehicleType.MOTORCYCLE,
        )



def test_admin_can_confirm_mp4_entry_and_exit(
    parking_service: ParkingService, seeded_users: dict[str, User]
) -> None:
    admin = seeded_users["admin"]
    parking_service.set_operation_source(SourceKind.MP4)
    entry = parking_service.create_entry(admin, "51A-999.98", VehicleType.CAR)
    parking_service.set_operation_source(SourceKind.LIVE)
    closed = parking_service.close_exit(admin, entry.id, source_kind=SourceKind.MP4)
    assert closed.status == ParkingStatus.DA_RA
    with pytest.raises(PermissionDeniedError):
        parking_service.create_entry(admin, "51A-999.97", VehicleType.CAR)
    with pytest.raises(PermissionDeniedError):
        parking_service.create_entry(seeded_users["manager"], "51A-999.96", VehicleType.CAR, source_kind=SourceKind.MP4)
    with pytest.raises(PermissionDeniedError):
        parking_service.create_entry(seeded_users["locked"], "51A-999.95", VehicleType.CAR, source_kind=SourceKind.MP4)

def test_database_rejects_duplicate_active_plate(
    session_manager: DatabaseSessionManager,
    parking_service: ParkingService,
    seeded_users: dict[str, User],
) -> None:
    staff = seeded_users["staff"]
    parking_service.create_entry(staff, "50A-123.45", VehicleType.CAR)
    duplicate = ParkingSession(
        id=None,
        session_code="SES-DIRECT-DUPLICATE",
        vehicle_id=None,
        customer_id=None,
        snapshot_plate="50A12345",
        snapshot_display_plate="50A-123.45",
        snapshot_vehicle_type=VehicleType.CAR,
        is_registered_customer=False,
    )

    with pytest.raises(IntegrityError):
        with session_manager.session() as session:
            SqlAlchemySessionRepository(session).save(duplicate)


def test_entry_transaction_failure_removes_saved_evidence(
    parking_service: ParkingService,
    evidence_storage: EvidenceStorage,
    seeded_users: dict[str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = evidence_storage.create_synthetic_image("51A-654.32", VehicleType.CAR)

    def fail_audit_add(*_args, **_kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail_audit_add)
    with pytest.raises(RuntimeError, match="simulated audit persistence failure"):
        parking_service.create_entry(
            seeded_users["staff"],
            "51A-654.32",
            VehicleType.CAR,
            image_data=image,
        )

    assert parking_service.list_active_sessions() == []
    assert list(evidence_storage.base_dir.rglob("*.jpg")) == []


def test_admin_deletes_active_session_and_records_audit(
    session_manager, parking_service, seeded_users
):
    entry = parking_service.create_entry(
        seeded_users["staff"], "51A-123.45", VehicleType.CAR, image_data=b"image"
    )
    with pytest.raises(PermissionDeniedError):
        parking_service.delete_active_session(seeded_users["manager"], entry.id)
    assert parking_service.get_session(entry.id) is not None
    parking_service.delete_active_session(seeded_users["admin"], entry.id)
    assert parking_service.get_session(entry.id) is None
    assert parking_service.get_capacity_summary().car_active == 0
    with session_manager.session() as session:
        from parking_app.infrastructure.persistence.repositories import SqlAlchemyEvidenceRepository
        assert SqlAlchemyEvidenceRepository(session).list_by_session(entry.id) == []
        audit = SqlAlchemyAuditRepository(session).list_recent(user_id=seeded_users["admin"].id)
        assert any(a.action == AuditAction.DELETE_SESSION and a.target_id == entry.session_code for a in audit)
    assert parking_service.create_entry(seeded_users["staff"], "51A-123.45", VehicleType.CAR)


def test_admin_cannot_delete_completed_session(parking_service, seeded_users):
    from parking_app.domain.exceptions import ValidationError
    entry = parking_service.create_entry(seeded_users["staff"], "51A-123.45", VehicleType.CAR)
    parking_service.close_exit(seeded_users["staff"], entry.id)
    with pytest.raises(ValidationError):
        parking_service.delete_active_session(seeded_users["admin"], entry.id)
    assert parking_service.get_session(entry.id).status == ParkingStatus.DA_RA
