"""Domain entities for user identity, customer registry, and audit tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from parking_app.domain.enums import (
    AuditAction,
    EvidenceType,
    ParkingStatus,
    UserRole,
    UserStatus,
    VehicleType,
)


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(UTC)


@dataclass
class User:
    """System operator, manager, or administrator."""

    id: int | None
    username: str
    password_hash: str
    full_name: str
    role: UserRole
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @property
    def is_manager(self) -> bool:
        return self.role in (UserRole.ADMIN, UserRole.MANAGER)


@dataclass
class Customer:
    """Registered vehicle owner or parking customer."""

    id: int | None
    customer_code: str
    full_name: str
    phone_number: str
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    vehicles: list[Vehicle] = field(default_factory=list)


@dataclass
class Vehicle:
    """Registered vehicle belonging to a customer."""

    id: int | None
    customer_id: int
    normalized_plate: str
    display_plate: str
    vehicle_type: VehicleType
    note: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class AuditEntry:
    """Immutable audit trail record capturing operator actions."""

    id: int | None
    user_id: int | None
    username: str | None
    action: AuditAction
    target_type: str
    target_id: str | None
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    reason: str | None = None
    timestamp: datetime = field(default_factory=utc_now)


@dataclass
class ParkingSession:
    """A single vehicle parking stay lifecycle from entry to exit."""

    id: int | None
    session_code: str
    vehicle_id: int | None
    customer_id: int | None
    snapshot_plate: str
    snapshot_display_plate: str
    snapshot_vehicle_type: VehicleType
    is_registered_customer: bool
    entry_time: datetime = field(default_factory=utc_now)
    exit_time: datetime | None = None
    status: ParkingStatus = ParkingStatus.DANG_GUI
    needs_attention: bool = False
    attention_reason: str | None = None
    entry_operator_id: int | None = None
    exit_operator_id: int | None = None
    entry_image_path: str | None = None
    exit_image_path: str | None = None
    note: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status == ParkingStatus.DANG_GUI

    @property
    def is_closed(self) -> bool:
        return self.status == ParkingStatus.DA_RA


@dataclass
class Evidence:
    """Photographic proof linked to a specific parking session."""

    id: int | None
    session_id: int
    evidence_type: EvidenceType
    file_path: str
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class CapacitySummary:
    """Current parking occupancy and capacity metrics."""

    motorcycle_capacity: int
    motorcycle_active: int
    car_capacity: int
    car_active: int
    total_capacity: int
    total_active: int
    motorcycle_remaining: int
    car_remaining: int
    total_remaining: int
    is_motorcycle_full: bool
    is_car_full: bool
    is_full: bool


@dataclass(frozen=True)
class ParkingStatistics:
    """Entry and exit counts for a selected period."""

    motorcycle_entries: int
    motorcycle_exits: int
    car_entries: int
    car_exits: int

    @property
    def total_entries(self) -> int:
        return self.motorcycle_entries + self.car_entries

    @property
    def total_exits(self) -> int:
        return self.motorcycle_exits + self.car_exits


@dataclass(frozen=True)
class ExceptionCase:
    """A reviewable operational anomaly backed by an immutable audit record."""

    reference: str
    category: str
    description: str
    plate: str
    operator: str
    timestamp: datetime
    evidence_path: str | None
    handled: bool
    session_code: str | None = None
