"""Authentication and user management application service."""

from __future__ import annotations

from parking_app.domain.enums import AuditAction, UserRole, UserStatus
from parking_app.domain.exceptions import (
    AccountLockedError,
    AuthenticationError,
    DuplicateUserError,
    PermissionDeniedError,
    UserNotFoundError,
    ValidationError,
)
from parking_app.domain.models import AuditEntry, User
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyUserRepository,
)
from parking_app.infrastructure.security import hash_password, verify_password


class AuthService:
    """Handles operator authentication, session identity, and user lifecycle."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    def authenticate(self, username: str, plain_password: str) -> User:
        """Authenticate user credentials and return the active User entity."""
        clean_user = username.strip().lower()
        if not clean_user or not plain_password:
            raise AuthenticationError("Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.")

        user: User | None = None
        with self.session_manager.session() as session:
            user_repo = SqlAlchemyUserRepository(session)
            user = user_repo.get_by_username(clean_user)

        if user is None or not verify_password(plain_password, user.password_hash):
            with self.session_manager.session() as session:
                audit_repo = SqlAlchemyAuditRepository(session)
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=user.id if user else None,
                        username=clean_user,
                        action=AuditAction.LOGIN_FAILED,
                        target_type="USER",
                        target_id=str(user.id) if user else None,
                        reason="Sai tên đăng nhập hoặc mật khẩu",
                    )
                )
            raise AuthenticationError("Tên đăng nhập hoặc mật khẩu không chính xác.")

        if user.status == UserStatus.LOCKED:
            with self.session_manager.session() as session:
                audit_repo = SqlAlchemyAuditRepository(session)
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=user.id,
                        username=user.username,
                        action=AuditAction.LOGIN_FAILED,
                        target_type="USER",
                        target_id=str(user.id),
                        reason="Đăng nhập tài khoản bị khóa",
                    )
                )
            raise AccountLockedError("Tài khoản này đã bị khóa. Vui lòng liên hệ Quản trị viên.")

        with self.session_manager.session() as session:
            audit_repo = SqlAlchemyAuditRepository(session)
            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=user.id,
                    username=user.username,
                    action=AuditAction.LOGIN,
                    target_type="USER",
                    target_id=str(user.id),
                    new_values={"role": user.role.value, "status": user.status.value},
                )
            )
        return user

    def record_logout(self, user: User) -> None:
        """Record explicit operator logout."""
        with self.session_manager.session() as session:
            audit_repo = SqlAlchemyAuditRepository(session)
            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=user.id,
                    username=user.username,
                    action=AuditAction.LOGOUT,
                    target_type="USER",
                    target_id=str(user.id),
                )
            )

    def create_user(
        self,
        actor: User,
        username: str,
        plain_password: str,
        full_name: str,
        role: UserRole,
    ) -> User:
        """Create a new operator account (Admin only)."""
        if not actor.is_admin:
            raise PermissionDeniedError("Chỉ Quản trị viên mới có quyền tạo tài khoản.")

        clean_username = username.strip().lower()
        clean_name = full_name.strip()

        if not clean_username:
            raise ValidationError("Tên đăng nhập không được để trống.")
        if len(clean_username) < 3:
            raise ValidationError("Tên đăng nhập phải có ít nhất 3 ký tự.")
        if not clean_name:
            raise ValidationError("Họ và tên không được để trống.")
        if not plain_password or len(plain_password) < 6:
            raise ValidationError("Mật khẩu phải có ít nhất 6 ký tự.")

        with self.session_manager.session() as session:
            user_repo = SqlAlchemyUserRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            if user_repo.get_by_username(clean_username) is not None:
                raise DuplicateUserError(f"Tên đăng nhập '{clean_username}' đã tồn tại.")

            hashed = hash_password(plain_password)
            new_user = User(
                id=None,
                username=clean_username,
                password_hash=hashed,
                full_name=clean_name,
                role=role,
                status=UserStatus.ACTIVE,
            )
            saved_user = user_repo.save(new_user)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.CREATE_USER,
                    target_type="USER",
                    target_id=str(saved_user.id),
                    new_values={
                        "username": saved_user.username,
                        "full_name": saved_user.full_name,
                        "role": saved_user.role.value,
                    },
                )
            )
            return saved_user

    def set_user_status(
        self,
        actor: User,
        target_user_id: int,
        status: UserStatus,
        reason: str | None = None,
    ) -> User:
        """Lock or unlock an account (Admin only)."""
        if not actor.is_admin:
            raise PermissionDeniedError("Chỉ Quản trị viên mới có quyền khóa/mở tài khoản.")

        if actor.id == target_user_id and status == UserStatus.LOCKED:
            raise ValidationError("Quản trị viên không thể tự khóa tài khoản của chính mình.")

        with self.session_manager.session() as session:
            user_repo = SqlAlchemyUserRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            target = user_repo.get_by_id(target_user_id)
            if target is None:
                raise UserNotFoundError(f"Không tìm thấy tài khoản với ID {target_user_id}.")

            old_status = target.status
            target.status = status
            updated = user_repo.save(target)

            action = (
                AuditAction.LOCK_USER if status == UserStatus.LOCKED else AuditAction.UNLOCK_USER
            )
            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=action,
                    target_type="USER",
                    target_id=str(updated.id),
                    old_values={"status": old_status.value},
                    new_values={"status": updated.status.value},
                    reason=reason,
                )
            )
            return updated

    def list_users(self, actor: User, include_locked: bool = True) -> list[User]:
        """List operator accounts (Admin or Manager)."""
        if not actor.is_manager:
            raise PermissionDeniedError("Bạn không có quyền xem danh sách tài khoản.")

        with self.session_manager.session() as session:
            user_repo = SqlAlchemyUserRepository(session)
            return user_repo.list_all(include_locked=include_locked)
