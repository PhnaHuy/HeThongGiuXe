"""Persistence module with SQLAlchemy 2.x and SQLite."""

from parking_app.infrastructure.persistence.database import (
    DatabaseSessionManager,
    create_sqlite_engine,
)
from parking_app.infrastructure.persistence.orm_models import (
    AuditLogModel,
    Base,
    CustomerModel,
    EvidenceModel,
    ParkingSessionModel,
    UserModel,
    VehicleModel,
)
from parking_app.infrastructure.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyCustomerRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyVehicleRepository,
)

__all__ = [
    "AuditLogModel",
    "Base",
    "CustomerModel",
    "DatabaseSessionManager",
    "EvidenceModel",
    "ParkingSessionModel",
    "SqlAlchemyAuditRepository",
    "SqlAlchemyCustomerRepository",
    "SqlAlchemyEvidenceRepository",
    "SqlAlchemySessionRepository",
    "SqlAlchemyUserRepository",
    "SqlAlchemyVehicleRepository",
    "UserModel",
    "VehicleModel",
    "create_sqlite_engine",
]
