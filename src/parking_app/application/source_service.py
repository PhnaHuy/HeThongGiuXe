"""QT-02/QT-03: source configuration and permission checks with atomic audit."""

from dataclasses import asdict

from sqlalchemy import select

from parking_app.domain.enums import AuditAction, UserRole, UserStatus
from parking_app.domain.exceptions import PermissionDeniedError, ValidationError
from parking_app.domain.models import AuditEntry, User
from parking_app.domain.video import (
    ParkingSpace,
    SourceConfig,
    SourceKind,
    SourcePurpose,
)
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.orm_models import SourceModel, UserModel
from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository


class SourceService:
    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    def authorize(self, actor: User, *, configure: bool = False) -> None:
        with self.session_manager.session() as session:
            self._authorize(session, actor, configure=configure)

    @staticmethod
    def _authorize(session, actor: User, *, configure: bool = False) -> None:
        account = session.get(UserModel, actor.id) if actor.id is not None else None
        if account is None or account.status != UserStatus.ACTIVE:
            raise PermissionDeniedError("Tài khoản không còn hoạt động. Hãy đăng nhập lại.")
        if account.role != actor.role or (configure and account.role != UserRole.ADMIN):
            raise PermissionDeniedError("Chỉ quản trị viên được lưu cấu hình nguồn hình.")

    @staticmethod
    def _config(row: SourceModel) -> SourceConfig:
        return SourceConfig(
            row.id,
            row.name,
            SourceKind(row.kind),
            row.endpoint,
            SourcePurpose(row.purpose),
            tuple(
                ParkingSpace(
                    code=space["code"],
                    points=tuple(tuple(point) for point in space["points"]),
                )
                for space in (row.parking_spaces or [])
            ),
        )

    def list_sources(self, actor: User) -> list[SourceConfig]:
        with self.session_manager.session() as session:
            self._authorize(session, actor)
            return [
                self._config(row)
                for row in session.scalars(select(SourceModel).order_by(SourceModel.name))
            ]

    def save_source(self, actor: User, config: SourceConfig) -> SourceConfig:
        config.validate()
        with self.session_manager.session() as session:
            self._authorize(session, actor, configure=True)
            row = session.get(SourceModel, config.id)
            old = self._audit_values(self._config(row)) if row else None
            if row is None:
                row = SourceModel(id=config.id)
                session.add(row)
            row.name = config.name.strip()
            row.kind = config.kind.value
            row.endpoint = config.endpoint.strip()
            row.purpose = config.purpose.value
            row.gate_line = None
            row.parking_spaces = [asdict(space) for space in config.parking_spaces]
            SqlAlchemyAuditRepository(session).add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.CONFIGURE_SOURCE,
                    target_type="video_source",
                    target_id=config.id,
                    old_values=old,
                    new_values=self._audit_values(config),
                )
            )
        return config

    def delete_source(self, actor: User, source_id: str) -> None:
        with self.session_manager.session() as session:
            self._authorize(session, actor, configure=True)
            row = session.get(SourceModel, source_id)
            if row is None:
                raise ValidationError("Nguồn hình không còn tồn tại.")
            SqlAlchemyAuditRepository(session).add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.CONFIGURE_SOURCE,
                    target_type="video_source",
                    target_id=source_id,
                    old_values=self._audit_values(self._config(row)),
                    new_values={"deleted": True},
                )
            )
            session.delete(row)

    @staticmethod
    def _audit_values(config: SourceConfig) -> dict:
        # Endpoint may contain camera credentials: never copy it into audit records.
        return {
            "name": config.name,
            "kind": config.kind.value,
            "purpose": config.purpose.value,
            "parking_spaces": [asdict(space) for space in config.parking_spaces],
        }
