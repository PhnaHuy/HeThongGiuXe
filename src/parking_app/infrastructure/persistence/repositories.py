"""SQLAlchemy repository implementations adhering to application contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from parking_app.domain.enums import AuditAction, ParkingStatus, VehicleType
from parking_app.domain.models import (
    AuditEntry,
    Customer,
    Evidence,
    ParkingSession,
    User,
    Vehicle,
)
from parking_app.domain.plate import normalize_plate
from parking_app.infrastructure.persistence.orm_models import (
    AuditLogModel,
    CustomerModel,
    EvidenceModel,
    ParkingSessionModel,
    UserModel,
    VehicleModel,
)


def _to_user_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        username=model.username,
        password_hash=model.password_hash,
        full_name=model.full_name,
        role=model.role,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_vehicle_domain(model: VehicleModel) -> Vehicle:
    return Vehicle(
        id=model.id,
        customer_id=model.customer_id,
        normalized_plate=model.normalized_plate,
        display_plate=model.display_plate,
        vehicle_type=model.vehicle_type,
        note=model.note,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_customer_domain(model: CustomerModel) -> Customer:
    vehicles = [_to_vehicle_domain(v) for v in getattr(model, "vehicles", [])]
    return Customer(
        id=model.id,
        customer_code=model.customer_code,
        full_name=model.full_name,
        phone_number=model.phone_number,
        note=model.note,
        created_at=model.created_at,
        updated_at=model.updated_at,
        vehicles=vehicles,
    )


def _to_audit_domain(model: AuditLogModel) -> AuditEntry:
    return AuditEntry(
        id=model.id,
        user_id=model.user_id,
        username=model.username,
        action=model.action,
        target_type=model.target_type,
        target_id=model.target_id,
        old_values=model.old_values,
        new_values=model.new_values,
        reason=model.reason,
        timestamp=model.timestamp,
    )


def _to_session_domain(model: ParkingSessionModel) -> ParkingSession:
    return ParkingSession(
        id=model.id,
        session_code=model.session_code,
        vehicle_id=model.vehicle_id,
        customer_id=model.customer_id,
        snapshot_plate=model.snapshot_plate,
        snapshot_display_plate=model.snapshot_display_plate,
        snapshot_vehicle_type=model.snapshot_vehicle_type,
        is_registered_customer=model.is_registered_customer,
        entry_time=model.entry_time,
        exit_time=model.exit_time,
        status=model.status,
        needs_attention=model.needs_attention,
        attention_reason=model.attention_reason,
        entry_operator_id=model.entry_operator_id,
        exit_operator_id=model.exit_operator_id,
        entry_image_path=model.entry_image_path,
        exit_image_path=model.exit_image_path,
        note=model.note,
    )


def _to_evidence_domain(model: EvidenceModel) -> Evidence:
    return Evidence(
        id=model.id,
        session_id=model.session_id,
        evidence_type=model.evidence_type,
        file_path=model.file_path,
        created_at=model.created_at,
    )


class SqlAlchemyUserRepository:
    """SQLAlchemy implementation of UserRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: int) -> User | None:
        stmt = select(UserModel).where(UserModel.id == user_id)
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_user_domain(res) if res else None

    def get_by_username(self, username: str) -> User | None:
        stmt = select(UserModel).where(UserModel.username == username.strip().lower())
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_user_domain(res) if res else None

    def list_all(self, include_locked: bool = True) -> list[User]:
        stmt = select(UserModel).order_by(UserModel.id)
        if not include_locked:
            stmt = stmt.where(UserModel.status == "ACTIVE")
        results = self.session.execute(stmt).scalars().all()
        return [_to_user_domain(r) for r in results]

    def save(self, user: User) -> User:
        username_clean = user.username.strip().lower()
        if user.id is None:
            model = UserModel(
                username=username_clean,
                password_hash=user.password_hash,
                full_name=user.full_name.strip(),
                role=user.role,
                status=user.status,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            self.session.add(model)
            self.session.flush()
            user.id = model.id
        else:
            model = self.session.get(UserModel, user.id)
            if model is None:
                raise ValueError(f"User with ID {user.id} does not exist.")
            model.username = username_clean
            model.password_hash = user.password_hash
            model.full_name = user.full_name.strip()
            model.role = user.role
            model.status = user.status
            model.updated_at = user.updated_at
            self.session.flush()
        return _to_user_domain(model)

    def count(self) -> int:
        stmt = select(UserModel.id)
        return len(self.session.execute(stmt).scalars().all())


class SqlAlchemyCustomerRepository:
    """SQLAlchemy implementation of CustomerRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, customer_id: int) -> Customer | None:
        stmt = (
            select(CustomerModel)
            .where(CustomerModel.id == customer_id)
            .options(selectinload(CustomerModel.vehicles))
        )
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_customer_domain(res) if res else None

    def get_by_code(self, customer_code: str) -> Customer | None:
        stmt = (
            select(CustomerModel)
            .where(CustomerModel.customer_code == customer_code.strip().upper())
            .options(selectinload(CustomerModel.vehicles))
        )
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_customer_domain(res) if res else None

    def search(self, query: str, limit: int = 50) -> list[Customer]:
        q = query.strip()
        if not q:
            return self.list_all(limit=limit)
        pattern = f"%{q}%"
        filters = [
            CustomerModel.customer_code.ilike(pattern),
            CustomerModel.full_name.ilike(pattern),
            CustomerModel.phone_number.ilike(pattern),
        ]
        normalized_plate = normalize_plate(q)
        if normalized_plate:
            filters.append(
                CustomerModel.vehicles.any(
                    VehicleModel.normalized_plate.ilike(f"%{normalized_plate}%")
                )
            )
        stmt = (
            select(CustomerModel)
            .where(or_(*filters))
            .options(selectinload(CustomerModel.vehicles))
            .order_by(CustomerModel.id.desc())
            .limit(limit)
        )
        results = self.session.execute(stmt).scalars().all()
        return [_to_customer_domain(r) for r in results]

    def list_all(self, limit: int = 100) -> list[Customer]:
        stmt = (
            select(CustomerModel)
            .options(selectinload(CustomerModel.vehicles))
            .order_by(CustomerModel.id.desc())
            .limit(limit)
        )
        results = self.session.execute(stmt).scalars().all()
        return [_to_customer_domain(r) for r in results]

    def save(self, customer: Customer) -> Customer:
        code_clean = customer.customer_code.strip().upper()
        if customer.id is None:
            model = CustomerModel(
                customer_code=code_clean,
                full_name=customer.full_name.strip(),
                phone_number=customer.phone_number.strip(),
                note=customer.note,
                created_at=customer.created_at,
                updated_at=customer.updated_at,
            )
            self.session.add(model)
            self.session.flush()
            customer.id = model.id
        else:
            model = self.session.get(CustomerModel, customer.id)
            if model is None:
                raise ValueError(f"Customer with ID {customer.id} does not exist.")
            model.customer_code = code_clean
            model.full_name = customer.full_name.strip()
            model.phone_number = customer.phone_number.strip()
            model.note = customer.note
            model.updated_at = customer.updated_at
            self.session.flush()
        return _to_customer_domain(model)

    def delete(self, customer_id: int) -> bool:
        model = self.session.get(CustomerModel, customer_id)
        if model:
            self.session.delete(model)
            self.session.flush()
            return True
        return False


class SqlAlchemyVehicleRepository:
    """SQLAlchemy implementation of VehicleRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, vehicle_id: int) -> Vehicle | None:
        model = self.session.get(VehicleModel, vehicle_id)
        return _to_vehicle_domain(model) if model else None

    def get_by_normalized_plate(self, normalized_plate: str) -> Vehicle | None:
        stmt = select(VehicleModel).where(
            VehicleModel.normalized_plate == normalized_plate.strip().upper()
        )
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_vehicle_domain(res) if res else None

    def list_by_customer(self, customer_id: int) -> list[Vehicle]:
        stmt = (
            select(VehicleModel)
            .where(VehicleModel.customer_id == customer_id)
            .order_by(VehicleModel.id)
        )
        results = self.session.execute(stmt).scalars().all()
        return [_to_vehicle_domain(r) for r in results]

    def save(self, vehicle: Vehicle) -> Vehicle:
        norm_plate = vehicle.normalized_plate.strip().upper()
        if vehicle.id is None:
            model = VehicleModel(
                customer_id=vehicle.customer_id,
                normalized_plate=norm_plate,
                display_plate=vehicle.display_plate.strip(),
                vehicle_type=vehicle.vehicle_type,
                note=vehicle.note,
                created_at=vehicle.created_at,
                updated_at=vehicle.updated_at,
            )
            self.session.add(model)
            self.session.flush()
            vehicle.id = model.id
        else:
            model = self.session.get(VehicleModel, vehicle.id)
            if model is None:
                raise ValueError(f"Vehicle with ID {vehicle.id} does not exist.")
            model.normalized_plate = norm_plate
            model.display_plate = vehicle.display_plate.strip()
            model.vehicle_type = vehicle.vehicle_type
            model.note = vehicle.note
            model.updated_at = vehicle.updated_at
            self.session.flush()
        return _to_vehicle_domain(model)

    def delete(self, vehicle_id: int) -> bool:
        model = self.session.get(VehicleModel, vehicle_id)
        if model:
            self.session.delete(model)
            self.session.flush()
            return True
        return False


class SqlAlchemyAuditRepository:
    """SQLAlchemy implementation of AuditRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entry: AuditEntry) -> AuditEntry:
        model = AuditLogModel(
            user_id=entry.user_id,
            username=entry.username,
            action=entry.action,
            target_type=entry.target_type,
            target_id=str(entry.target_id) if entry.target_id is not None else None,
            old_values=entry.old_values,
            new_values=entry.new_values,
            reason=entry.reason,
            timestamp=entry.timestamp,
        )
        self.session.add(model)
        self.session.flush()
        entry.id = model.id
        return _to_audit_domain(model)

    def list_recent(
        self,
        limit: int = 100,
        user_id: int | None = None,
        action: AuditAction | None = None,
        from_time: datetime | None = None,
        before_time: datetime | None = None,
    ) -> list[AuditEntry]:
        stmt = select(AuditLogModel).order_by(AuditLogModel.timestamp.desc())
        if user_id is not None:
            stmt = stmt.where(AuditLogModel.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLogModel.action == action)
        if from_time is not None:
            stmt = stmt.where(AuditLogModel.timestamp >= _database_datetime(from_time))
        if before_time is not None:
            stmt = stmt.where(AuditLogModel.timestamp < _database_datetime(before_time))
        stmt = stmt.limit(limit)
        results = self.session.execute(stmt).scalars().all()
        return [_to_audit_domain(r) for r in results]


def _database_datetime(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo is not None else value


class SqlAlchemySessionRepository:
    """SQLAlchemy implementation of ParkingSessionRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, session_id: int) -> ParkingSession | None:
        model = self.session.get(ParkingSessionModel, session_id)
        return _to_session_domain(model) if model else None

    def get_by_code(self, session_code: str) -> ParkingSession | None:
        stmt = select(ParkingSessionModel).where(
            ParkingSessionModel.session_code == session_code.strip()
        )
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_session_domain(res) if res else None

    def get_active_by_plate(self, normalized_plate: str) -> ParkingSession | None:
        norm = normalized_plate.strip().upper()
        stmt = select(ParkingSessionModel).where(
            ParkingSessionModel.snapshot_plate == norm,
            ParkingSessionModel.status == ParkingStatus.DANG_GUI,
        )
        res = self.session.execute(stmt).scalar_one_or_none()
        return _to_session_domain(res) if res else None

    def count_active(self, vehicle_type: VehicleType | None = None) -> int:
        stmt = select(func.count(ParkingSessionModel.id)).where(
            ParkingSessionModel.status == ParkingStatus.DANG_GUI
        )
        if vehicle_type is not None:
            stmt = stmt.where(ParkingSessionModel.snapshot_vehicle_type == vehicle_type)
        return self.session.execute(stmt).scalar() or 0

    def count_entries(
        self,
        vehicle_type: VehicleType,
        from_time: datetime | None,
        before_time: datetime | None,
    ) -> int:
        stmt = select(func.count(ParkingSessionModel.id)).where(
            ParkingSessionModel.snapshot_vehicle_type == vehicle_type
        )
        if from_time is not None:
            stmt = stmt.where(ParkingSessionModel.entry_time >= _database_datetime(from_time))
        if before_time is not None:
            stmt = stmt.where(ParkingSessionModel.entry_time < _database_datetime(before_time))
        return self.session.execute(stmt).scalar() or 0

    def count_exits(
        self,
        vehicle_type: VehicleType,
        from_time: datetime | None,
        before_time: datetime | None,
    ) -> int:
        stmt = select(func.count(ParkingSessionModel.id)).where(
            ParkingSessionModel.snapshot_vehicle_type == vehicle_type,
            ParkingSessionModel.exit_time.is_not(None),
        )
        if from_time is not None:
            stmt = stmt.where(ParkingSessionModel.exit_time >= _database_datetime(from_time))
        if before_time is not None:
            stmt = stmt.where(ParkingSessionModel.exit_time < _database_datetime(before_time))
        return self.session.execute(stmt).scalar() or 0

    def sessions_with_activity(
        self, from_time: datetime | None, before_time: datetime | None
    ) -> list[ParkingSession]:
        """Return each session once if its entry or exit falls within the period."""

        def in_period(column):
            conditions = [column.is_not(None)]
            if from_time is not None:
                conditions.append(column >= _database_datetime(from_time))
            if before_time is not None:
                conditions.append(column < _database_datetime(before_time))
            return and_(*conditions)

        stmt = (
            select(ParkingSessionModel)
            .where(
                or_(
                    in_period(ParkingSessionModel.entry_time),
                    in_period(ParkingSessionModel.exit_time),
                )
            )
            .order_by(ParkingSessionModel.entry_time.desc(), ParkingSessionModel.id.desc())
        )
        return [_to_session_domain(row) for row in self.session.execute(stmt).scalars().all()]

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
    ) -> list[ParkingSession]:
        stmt = select(ParkingSessionModel).order_by(ParkingSessionModel.entry_time.desc())
        q = plate_query.strip().upper()
        if q:
            normalized_query = normalize_plate(q)
            plate_filters = [
                ParkingSessionModel.snapshot_plate.ilike(f"%{q}%"),
                ParkingSessionModel.session_code.ilike(f"%{q}%"),
            ]
            if normalized_query and normalized_query != q:
                plate_filters.append(
                    ParkingSessionModel.snapshot_plate.ilike(f"%{normalized_query}%")
                )
            stmt = stmt.where(or_(*plate_filters))
        customer = customer_query.strip()
        if customer:
            needle = customer.casefold()
            customer_rows = self.session.execute(
                select(
                    CustomerModel.id,
                    CustomerModel.customer_code,
                    CustomerModel.full_name,
                    CustomerModel.phone_number,
                )
            ).all()
            customer_ids = [
                customer_id
                for customer_id, code, name, phone in customer_rows
                if any(
                    needle in value.casefold() for value in (code, name, phone) if value is not None
                )
            ]
            stmt = stmt.where(ParkingSessionModel.customer_id.in_(customer_ids))
        if status is not None:
            stmt = stmt.where(ParkingSessionModel.status == status)
        if vehicle_type is not None:
            stmt = stmt.where(ParkingSessionModel.snapshot_vehicle_type == vehicle_type)
        if needs_attention_only:
            stmt = stmt.where(ParkingSessionModel.needs_attention.is_(True))
        if entry_from is not None:
            if entry_from.tzinfo is not None:
                entry_from = entry_from.astimezone(UTC).replace(tzinfo=None)
            stmt = stmt.where(ParkingSessionModel.entry_time >= entry_from)
        if entry_before is not None:
            if entry_before.tzinfo is not None:
                entry_before = entry_before.astimezone(UTC).replace(tzinfo=None)
            stmt = stmt.where(ParkingSessionModel.entry_time < entry_before)
        stmt = stmt.limit(limit)
        results = self.session.execute(stmt).scalars().all()
        return [_to_session_domain(r) for r in results]

    def list_active(self, limit: int = 100) -> list[ParkingSession]:
        stmt = (
            select(ParkingSessionModel)
            .where(ParkingSessionModel.status == ParkingStatus.DANG_GUI)
            .order_by(ParkingSessionModel.entry_time.desc())
            .limit(limit)
        )
        results = self.session.execute(stmt).scalars().all()
        return [_to_session_domain(r) for r in results]

    def delete_active(self, session_id: int) -> bool:
        """Delete only a session that is still active."""
        from sqlalchemy import delete

        result = self.session.execute(
            delete(ParkingSessionModel).where(
                ParkingSessionModel.id == session_id,
                ParkingSessionModel.status == ParkingStatus.DANG_GUI,
            )
        )
        return result.rowcount == 1

    def save(self, session: ParkingSession) -> ParkingSession:
        if session.id is None:
            model = ParkingSessionModel(
                session_code=session.session_code,
                vehicle_id=session.vehicle_id,
                customer_id=session.customer_id,
                snapshot_plate=session.snapshot_plate.strip().upper(),
                snapshot_display_plate=session.snapshot_display_plate.strip(),
                snapshot_vehicle_type=session.snapshot_vehicle_type,
                is_registered_customer=session.is_registered_customer,
                entry_time=session.entry_time,
                exit_time=session.exit_time,
                status=session.status,
                needs_attention=session.needs_attention,
                attention_reason=session.attention_reason,
                entry_operator_id=session.entry_operator_id,
                exit_operator_id=session.exit_operator_id,
                entry_image_path=session.entry_image_path,
                exit_image_path=session.exit_image_path,
                note=session.note,
            )
            self.session.add(model)
            self.session.flush()
            session.id = model.id
        else:
            model = self.session.get(ParkingSessionModel, session.id)
            if model is None:
                raise ValueError(f"Parking session with ID {session.id} does not exist.")
            model.snapshot_plate = session.snapshot_plate.strip().upper()
            model.snapshot_display_plate = session.snapshot_display_plate.strip()
            model.snapshot_vehicle_type = session.snapshot_vehicle_type
            model.exit_time = session.exit_time
            model.status = session.status
            model.needs_attention = session.needs_attention
            model.attention_reason = session.attention_reason
            model.exit_operator_id = session.exit_operator_id
            model.exit_image_path = session.exit_image_path
            model.note = session.note
            self.session.flush()
        return _to_session_domain(model)


class SqlAlchemyEvidenceRepository:
    """SQLAlchemy implementation of EvidenceRepository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, evidence: Evidence) -> Evidence:
        model = EvidenceModel(
            session_id=evidence.session_id,
            evidence_type=evidence.evidence_type,
            file_path=evidence.file_path,
            created_at=evidence.created_at,
        )
        self.session.add(model)
        self.session.flush()
        evidence.id = model.id
        return _to_evidence_domain(model)

    def list_by_session(self, session_id: int) -> list[Evidence]:
        stmt = (
            select(EvidenceModel)
            .where(EvidenceModel.session_id == session_id)
            .order_by(EvidenceModel.id)
        )
        results = self.session.execute(stmt).scalars().all()
        return [_to_evidence_domain(r) for r in results]
