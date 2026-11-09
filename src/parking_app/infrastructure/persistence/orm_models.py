"""SQLAlchemy 2.x Declarative ORM models for parking system."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from parking_app.domain.enums import (
    AuditAction,
    EvidenceType,
    ParkingStatus,
    UserRole,
    UserStatus,
    VehicleType,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class SourceModel(Base):
    """G3 additive table; existing parking data does not need rebuilding."""

    __tablename__ = "video_sources"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    gate_line: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parking_spaces: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)


class ParkingCapacityModel(Base):
    """Persisted per-vehicle parking capacity configuration."""

    __tablename__ = "parking_capacity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    motorcycle_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    car_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserModel(Base):
    """Database model for user accounts."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False),
        nullable=False,
        default=UserStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class CustomerModel(Base):
    """Database model for registered customers."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_code: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    phone_number: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    vehicles: Mapped[list[VehicleModel]] = relationship(
        "VehicleModel",
        back_populates="customer",
        cascade="all, delete-orphan",
        order_by="VehicleModel.id",
    )


class VehicleModel(Base):
    """Database model for registered customer vehicles."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    normalized_plate: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        index=True,
    )
    display_plate: Mapped[str] = mapped_column(String(30), nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        Enum(VehicleType, native_enum=False),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    customer: Mapped[CustomerModel] = relationship("CustomerModel", back_populates="vehicles")


class AuditLogModel(Base):
    """Database model for immutable audit log entries."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )

    __table_args__ = (Index("ix_audit_logs_action_timestamp", "action", "timestamp"),)


class ParkingSessionModel(Base):
    """Database model for active and completed vehicle parking sessions."""

    __tablename__ = "parking_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    snapshot_plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    snapshot_display_plate: Mapped[str] = mapped_column(String(30), nullable=False)
    snapshot_vehicle_type: Mapped[VehicleType] = mapped_column(
        Enum(VehicleType, native_enum=False), nullable=False
    )
    is_registered_customer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    exit_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    status: Mapped[ParkingStatus] = mapped_column(
        Enum(ParkingStatus, native_enum=False),
        default=ParkingStatus.DANG_GUI,
        nullable=False,
        index=True,
    )
    needs_attention: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    attention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    exit_operator_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entry_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exit_image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_active_plate_status", "snapshot_plate", "status"),
        Index(
            "uq_parking_sessions_one_active_plate",
            "snapshot_plate",
            unique=True,
            sqlite_where=text("status = 'DANG_GUI'"),
        ),
    )


class EvidenceModel(Base):
    """Database model linking photographic evidence records with a session."""

    __tablename__ = "evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("parking_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(
        Enum(EvidenceType, native_enum=False), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
