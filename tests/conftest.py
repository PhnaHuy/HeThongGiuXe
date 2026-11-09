"""Pytest fixtures for parking application tests."""

from __future__ import annotations

import pytest

from parking_app.domain.enums import UserRole, UserStatus
from parking_app.domain.models import User
from parking_app.infrastructure.persistence.database import (
    DatabaseSessionManager,
    create_sqlite_engine,
)
from parking_app.infrastructure.persistence.repositories import SqlAlchemyUserRepository
from parking_app.infrastructure.security import hash_password


@pytest.fixture
def session_manager() -> DatabaseSessionManager:
    """Create an in-memory SQLite database session manager with clean schema."""
    engine = create_sqlite_engine(":memory:")
    sm = DatabaseSessionManager(engine)
    sm.init_tables()
    return sm


@pytest.fixture
def seeded_users(session_manager: DatabaseSessionManager) -> dict[str, User]:
    """Seed test operator accounts: admin, manager, staff, locked_staff."""
    with session_manager.session() as session:
        repo = SqlAlchemyUserRepository(session)
        admin = repo.save(
            User(
                id=None,
                username="admin_user",
                password_hash=hash_password("admin_pass"),
                full_name="Quản Trị Viên Mẫu",
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            )
        )
        manager = repo.save(
            User(
                id=None,
                username="manager_user",
                password_hash=hash_password("manager_pass"),
                full_name="Quản Lý Mẫu",
                role=UserRole.MANAGER,
                status=UserStatus.ACTIVE,
            )
        )
        staff = repo.save(
            User(
                id=None,
                username="staff_user",
                password_hash=hash_password("staff_pass"),
                full_name="Nhân Viên Mẫu",
                role=UserRole.STAFF,
                status=UserStatus.ACTIVE,
            )
        )
        locked = repo.save(
            User(
                id=None,
                username="locked_user",
                password_hash=hash_password("locked_pass"),
                full_name="Nhân Viên Bị Khóa",
                role=UserRole.STAFF,
                status=UserStatus.LOCKED,
            )
        )
    return {
        "admin": admin,
        "manager": manager,
        "staff": staff,
        "locked": locked,
    }
