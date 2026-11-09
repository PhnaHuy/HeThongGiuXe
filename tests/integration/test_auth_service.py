"""Integration tests for AuthService (NV-01, QT-01)."""

import pytest

from parking_app.application.auth_service import AuthService
from parking_app.domain.enums import AuditAction, UserRole, UserStatus
from parking_app.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    DuplicateUserError,
    PermissionDeniedError,
    ValidationError,
)
from parking_app.domain.models import User
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository


def test_login_successful(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    user = service.authenticate("staff_user", "staff_pass")
    assert user.id == seeded_users["staff"].id
    assert user.role == UserRole.STAFF
    assert user.is_active is True

    # Verify audit log recorded LOGIN
    with session_manager.session() as session:
        logs = SqlAlchemyAuditRepository(session).list_recent()
        login_logs = [entry for entry in logs if entry.action == AuditAction.LOGIN]
        assert len(login_logs) == 1
        assert login_logs[0].username == "staff_user"


def test_login_wrong_password_fails(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    with pytest.raises(AuthenticationError, match="không chính xác"):
        service.authenticate("staff_user", "incorrect_pwd")

    with session_manager.session() as session:
        logs = SqlAlchemyAuditRepository(session).list_recent()
        failed_logs = [entry for entry in logs if entry.action == AuditAction.LOGIN_FAILED]
        assert len(failed_logs) == 1
        assert failed_logs[0].username == "staff_user"


def test_login_nonexistent_user_fails(session_manager: DatabaseSessionManager) -> None:
    service = AuthService(session_manager)
    with pytest.raises(AuthenticationError, match="không chính xác"):
        service.authenticate("nonexistent", "some_pass")


def test_login_locked_account_fails(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    with pytest.raises(AccountLockedError, match="đã bị khóa"):
        service.authenticate("locked_user", "locked_pass")


def test_admin_can_create_user(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    admin = seeded_users["admin"]

    new_user = service.create_user(
        actor=admin,
        username="new_staff",
        plain_password="secure_password",
        full_name="Nhân Viên Mới",
        role=UserRole.STAFF,
    )
    assert new_user.id is not None
    assert new_user.username == "new_staff"
    assert new_user.role == UserRole.STAFF

    # Verify new user can log in
    logged_in = service.authenticate("new_staff", "secure_password")
    assert logged_in.id == new_user.id


def test_non_admin_cannot_create_user(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    staff = seeded_users["staff"]

    with pytest.raises(PermissionDeniedError, match="Chỉ Quản trị viên"):
        service.create_user(
            actor=staff,
            username="illegal_user",
            plain_password="some_pass_123",
            full_name="Illegal",
            role=UserRole.STAFF,
        )


def test_create_user_duplicate_username_fails(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    admin = seeded_users["admin"]

    with pytest.raises(DuplicateUserError, match="đã tồn tại"):
        service.create_user(
            actor=admin,
            username="staff_user",  # Already exists in fixture
            plain_password="password123",
            full_name="Trùng Tên",
            role=UserRole.STAFF,
        )


def test_admin_can_lock_and_unlock_account(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    admin = seeded_users["admin"]
    staff = seeded_users["staff"]

    # Lock
    locked_staff = service.set_user_status(
        actor=admin,
        target_user_id=staff.id,
        status=UserStatus.LOCKED,
        reason="Nghỉ việc tạm thời",
    )
    assert locked_staff.status == UserStatus.LOCKED

    # Verify staff cannot log in now
    with pytest.raises(AccountLockedError):
        service.authenticate("staff_user", "staff_pass")

    # Unlock
    unlocked_staff = service.set_user_status(
        actor=admin,
        target_user_id=staff.id,
        status=UserStatus.ACTIVE,
        reason="Đi làm lại",
    )
    assert unlocked_staff.status == UserStatus.ACTIVE

    # Verify staff can log in again
    user = service.authenticate("staff_user", "staff_pass")
    assert user.is_active is True


def test_admin_cannot_self_lock(
    session_manager: DatabaseSessionManager,
    seeded_users: dict[str, User],
) -> None:
    service = AuthService(session_manager)
    admin = seeded_users["admin"]

    with pytest.raises(ValidationError, match="không thể tự khóa tài khoản"):
        service.set_user_status(
            actor=admin,
            target_user_id=admin.id,
            status=UserStatus.LOCKED,
        )
