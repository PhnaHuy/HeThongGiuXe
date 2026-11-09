from dataclasses import replace

import pytest
from sqlalchemy import func, select

from parking_app.application.parking_service import ParkingService
from parking_app.application.source_service import SourceService
from parking_app.domain.enums import ParkingStatus, UserStatus, VehicleType
from parking_app.domain.exceptions import PermissionDeniedError
from parking_app.domain.video import (
    GateLine,
    ParkingSpace,
    SourceConfig,
    SourceKind,
    SourcePurpose,
)
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import (
    DatabaseSessionManager,
    create_sqlite_engine,
)
from parking_app.infrastructure.persistence.orm_models import (
    AuditLogModel,
    ParkingSessionModel,
    SourceModel,
    UserModel,
)


def test_admin_saves_per_camera_lines_with_private_audit(session_manager, seeded_users):
    service = SourceService(session_manager)
    config = SourceConfig(
        "cam1", "Cổng", SourceKind.LIVE, "rtsp://user:private-password@host/live", line=GateLine()
    )
    service.save_source(seeded_users["admin"], config)
    service.save_source(seeded_users["admin"], replace(config, id="cam2", line=None))
    service.save_source(seeded_users["admin"], replace(config, line=GateLine(entry_positive=False)))
    sources = service.list_sources(seeded_users["staff"])
    assert {c.id: c.line for c in sources} == {
        "cam1": GateLine(entry_positive=False),
        "cam2": None,
    }
    with session_manager.session() as session:
        logs = list(session.scalars(select(AuditLogModel)))
        assert len(logs) == 3
        assert "private-password" not in str([(log.old_values, log.new_values) for log in logs])
        assert logs[-1].old_values["line"]["entry_positive"] is True
        assert logs[-1].new_values["line"]["entry_positive"] is False
    service.delete_source(seeded_users["admin"], "cam1")
    assert len(service.list_sources(seeded_users["staff"])) == 1


def test_multiple_camera_urls_are_saved_independently(session_manager, seeded_users):
    service = SourceService(session_manager)
    configs = [
        SourceConfig("entry", "Cổng vào", SourceKind.LIVE, "rtsp://one:pw@192.168.1.10:8554/live"),
        SourceConfig("exit", "Cổng ra", SourceKind.LIVE, "rtsp://two:pw@192.168.1.11:554/stream1"),
        SourceConfig("lot", "Khu đỗ", SourceKind.LIVE, "http://192.168.1.12:8080/video"),
    ]
    for config in configs:
        service.save_source(seeded_users["admin"], config)

    assert {c.id: c.endpoint for c in service.list_sources(seeded_users["staff"])} == {
        c.id: c.endpoint for c in configs
    }


@pytest.mark.parametrize("role", ["staff", "manager", "locked"])
def test_source_configuration_denied_at_service(session_manager, seeded_users, role):
    with pytest.raises(PermissionDeniedError):
        SourceService(session_manager).save_source(
            seeded_users[role],
            SourceConfig("cam", "Camera", SourceKind.LIVE, "0"),
        )


def test_source_service_rechecks_account_lock(session_manager, seeded_users):
    actor = seeded_users["admin"]
    with session_manager.session() as session:
        session.get(UserModel, actor.id).status = UserStatus.LOCKED
    assert actor.is_active  # Simulates a session opened before the administrator locked it.
    with pytest.raises(PermissionDeniedError):
        SourceService(session_manager).list_sources(actor)


def test_source_service_persists_parking_polygons_and_audits_changes(session_manager, seeded_users):
    service = SourceService(session_manager)
    config = SourceConfig(
        "lot-camera",
        "Khu A",
        SourceKind.LIVE,
        "0",
        purpose=SourcePurpose.PARKING,
        parking_spaces=(ParkingSpace("A01", ((0.1, 0.1), (0.4, 0.1), (0.4, 0.5), (0.1, 0.5))),),
    )

    service.save_source(seeded_users["admin"], config)

    assert service.list_sources(seeded_users["staff"]) == [config]
    with session_manager.session() as session:
        log = session.scalar(select(AuditLogModel))
    assert log.new_values["parking_spaces"] == [
        {
            "code": "A01",
            "points": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5], [0.1, 0.5]],
        }
    ]


def test_legacy_video_sources_migrate_without_losing_saved_sources(tmp_path, seeded_users):
    engine = create_sqlite_engine(tmp_path / "legacy.sqlite")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE video_sources (
                id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                kind VARCHAR(10) NOT NULL,
                endpoint TEXT NOT NULL,
                purpose VARCHAR(20) NOT NULL,
                gate_line JSON
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO video_sources VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy", "Cổng cũ", "LIVE", "0", "ENTRY", None),
        )

    manager = DatabaseSessionManager(engine)
    manager.init_tables()
    manager.init_tables()
    try:
        actor = seeded_users["admin"]
        with manager.session() as session:
            session.add(
                UserModel(
                    id=actor.id,
                    username=actor.username,
                    password_hash=actor.password_hash,
                    full_name=actor.full_name,
                    role=actor.role,
                    status=actor.status,
                )
            )
        stored = SourceService(manager).list_sources(seeded_users["admin"])
        assert stored == [
            SourceConfig("legacy", "Cổng cũ", SourceKind.LIVE, "0", parking_spaces=())
        ]
    finally:
        engine.dispose()


def test_source_and_audit_are_atomic(session_manager, seeded_users, monkeypatch):
    from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository

    def fail(*args):
        raise RuntimeError("audit failure")

    monkeypatch.setattr(SqlAlchemyAuditRepository, "add", fail)
    with pytest.raises(RuntimeError):
        SourceService(session_manager).save_source(
            seeded_users["admin"],
            SourceConfig("cam", "Camera", SourceKind.LIVE, "0"),
        )
    with session_manager.session() as session:
        assert session.scalar(select(func.count()).select_from(SourceModel)) == 0


def test_mp4_can_create_and_close_operational_sessions(session_manager, seeded_users, tmp_path):
    storage = EvidenceStorage(tmp_path / "evidence")
    service = ParkingService(session_manager, storage)
    staff = seeded_users["staff"]
    picture = storage.create_synthetic_image("51A12345", VehicleType.CAR)
    stay = service.create_entry(staff, "51A12345", VehicleType.CAR, picture)
    service.set_operation_source(SourceKind.MP4)
    mp4_stay = service.create_entry(staff, "51A12346", VehicleType.CAR, picture)
    service.flag_session_attention(staff, mp4_stay.id, "Mô phỏng")
    service.record_unmatched_exit(staff, "Mô phỏng", image_data=picture)
    service.close_exit(staff, stay.id, picture)
    service.set_operation_source(SourceKind.LIVE)
    service.close_exit(staff, mp4_stay.id, picture, source_kind=SourceKind.MP4)
    with session_manager.session() as session:
        assert session.scalar(select(func.count()).select_from(ParkingSessionModel)) == 2
        assert session.get(ParkingSessionModel, stay.id).status == ParkingStatus.DA_RA
        assert session.get(ParkingSessionModel, mp4_stay.id).status == ParkingStatus.DA_RA
    assert service.get_capacity_summary().total_active == 0
