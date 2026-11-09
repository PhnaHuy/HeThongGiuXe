"""Application layer interfaces and repository contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from parking_app.domain.enums import AuditAction, ParkingStatus, VehicleType
from parking_app.domain.models import AuditEntry, Customer, Evidence, ParkingSession, User, Vehicle


class UserRepository(Protocol):
    """Contract for user identity storage."""

    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_username(self, username: str) -> User | None: ...

    def list_all(self, include_locked: bool = True) -> list[User]: ...

    def save(self, user: User) -> User: ...

    def count(self) -> int: ...


class CustomerRepository(Protocol):
    """Contract for customer profile persistence."""

    def get_by_id(self, customer_id: int) -> Customer | None: ...

    def get_by_code(self, customer_code: str) -> Customer | None: ...

    def search(self, query: str, limit: int = 50) -> list[Customer]: ...

    def list_all(self, limit: int = 100) -> list[Customer]: ...

    def save(self, customer: Customer) -> Customer: ...

    def delete(self, customer_id: int) -> bool: ...


class VehicleRepository(Protocol):
    """Contract for customer vehicle persistence."""

    def get_by_id(self, vehicle_id: int) -> Vehicle | None: ...

    def get_by_normalized_plate(self, normalized_plate: str) -> Vehicle | None: ...

    def list_by_customer(self, customer_id: int) -> list[Vehicle]: ...

    def save(self, vehicle: Vehicle) -> Vehicle: ...

    def delete(self, vehicle_id: int) -> bool: ...


class AuditRepository(Protocol):
    """Contract for audit trail persistence."""

    def add(self, entry: AuditEntry) -> AuditEntry: ...

    def list_recent(
        self,
        limit: int = 100,
        user_id: int | None = None,
        action: AuditAction | None = None,
        from_time: datetime | None = None,
        before_time: datetime | None = None,
    ) -> list[AuditEntry]: ...


class ParkingSessionRepository(Protocol):
    """Contract for vehicle parking session lifecycle persistence."""

    def get_by_id(self, session_id: int) -> ParkingSession | None: ...

    def get_by_code(self, session_code: str) -> ParkingSession | None: ...

    def get_active_by_plate(self, normalized_plate: str) -> ParkingSession | None: ...

    def count_active(self, vehicle_type: VehicleType | None = None) -> int: ...

    def search_sessions(
        self,
        plate_query: str = "",
        status: ParkingStatus | None = None,
        vehicle_type: VehicleType | None = None,
        needs_attention_only: bool = False,
        limit: int = 100,
        customer_query: str = "",
        entry_from: datetime | None = None,
        entry_before: datetime | None = None,
    ) -> list[ParkingSession]: ...

    def list_active(self, limit: int = 100) -> list[ParkingSession]: ...

    def save(self, session: ParkingSession) -> ParkingSession: ...


class EvidenceRepository(Protocol):
    """Contract for photographic evidence record persistence."""

    def add(self, evidence: Evidence) -> Evidence: ...

    def list_by_session(self, session_id: int) -> list[Evidence]: ...
