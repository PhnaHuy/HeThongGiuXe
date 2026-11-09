"""Customer and vehicle management application service."""

from __future__ import annotations

from parking_app.domain.enums import AuditAction, UserRole, UserStatus, VehicleType
from parking_app.domain.exceptions import (
    CustomerNotFoundError,
    DuplicateCustomerError,
    DuplicatePlateError,
    PermissionDeniedError,
    ValidationError,
    VehicleNotFoundError,
)
from parking_app.domain.models import AuditEntry, Customer, User, Vehicle
from parking_app.domain.plate import normalize_plate, validate_normalized_plate
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyCustomerRepository,
    SqlAlchemyVehicleRepository,
)


class CustomerService:
    """Manages customer profiles and multiple vehicles per customer."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    def register_customer(
        self,
        actor: User,
        customer_code: str,
        full_name: str,
        phone_number: str,
        note: str | None = None,
    ) -> Customer:
        """Register a new customer profile."""
        code_clean = customer_code.strip().upper()
        name_clean = full_name.strip()
        phone_clean = phone_number.strip()

        if not code_clean:
            raise ValidationError("Mã khách hàng không được để trống.")
        if not name_clean:
            raise ValidationError("Họ và tên khách hàng không được để trống.")
        if not phone_clean:
            raise ValidationError("Số điện thoại không được để trống.")

        with self.session_manager.session() as session:
            cust_repo = SqlAlchemyCustomerRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            if cust_repo.get_by_code(code_clean) is not None:
                raise DuplicateCustomerError(f"Mã khách hàng '{code_clean}' đã tồn tại.")

            customer = Customer(
                id=None,
                customer_code=code_clean,
                full_name=name_clean,
                phone_number=phone_clean,
                note=note.strip() if note else None,
            )
            saved = cust_repo.save(customer)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.CREATE_CUSTOMER,
                    target_type="CUSTOMER",
                    target_id=str(saved.id),
                    new_values={
                        "customer_code": saved.customer_code,
                        "full_name": saved.full_name,
                        "phone_number": saved.phone_number,
                    },
                )
            )
            return saved

    def update_customer(
        self,
        actor: User,
        customer_id: int,
        full_name: str,
        phone_number: str,
        note: str | None = None,
    ) -> Customer:
        """Update customer personal info."""
        self._require_admin(actor)
        name_clean = full_name.strip()
        phone_clean = phone_number.strip()

        if not name_clean:
            raise ValidationError("Họ và tên khách hàng không được để trống.")
        if not phone_clean:
            raise ValidationError("Số điện thoại không được để trống.")

        with self.session_manager.session() as session:
            cust_repo = SqlAlchemyCustomerRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            customer = cust_repo.get_by_id(customer_id)
            if customer is None:
                raise CustomerNotFoundError(f"Không tìm thấy khách hàng với ID {customer_id}.")

            old_values = {
                "full_name": customer.full_name,
                "phone_number": customer.phone_number,
                "note": customer.note,
            }

            customer.full_name = name_clean
            customer.phone_number = phone_clean
            customer.note = note.strip() if note else None
            saved = cust_repo.save(customer)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.UPDATE_CUSTOMER,
                    target_type="CUSTOMER",
                    target_id=str(saved.id),
                    old_values=old_values,
                    new_values={
                        "full_name": saved.full_name,
                        "phone_number": saved.phone_number,
                        "note": saved.note,
                    },
                )
            )
            return saved

    def register_vehicle(
        self,
        actor: User,
        customer_id: int,
        raw_plate: str,
        vehicle_type: VehicleType,
        note: str | None = None,
    ) -> Vehicle:
        """Register a new vehicle under an existing customer."""
        norm_plate = normalize_plate(raw_plate)
        validate_normalized_plate(norm_plate)

        with self.session_manager.session() as session:
            cust_repo = SqlAlchemyCustomerRepository(session)
            veh_repo = SqlAlchemyVehicleRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            customer = cust_repo.get_by_id(customer_id)
            if customer is None:
                raise CustomerNotFoundError(f"Không tìm thấy khách hàng với ID {customer_id}.")

            existing = veh_repo.get_by_normalized_plate(norm_plate)
            if existing is not None:
                owner = cust_repo.get_by_id(existing.customer_id)
                owner_info = (
                    f" (thuộc khách hàng {owner.full_name} - {owner.customer_code})"
                    if owner
                    else ""
                )
                raise DuplicatePlateError(
                    f"Biển số '{norm_plate}' đã được đăng ký trong hệ thống{owner_info}."
                )

            vehicle = Vehicle(
                id=None,
                customer_id=customer_id,
                normalized_plate=norm_plate,
                display_plate=raw_plate.strip().upper(),
                vehicle_type=vehicle_type,
                note=note.strip() if note else None,
            )
            saved = veh_repo.save(vehicle)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.REGISTER_VEHICLE,
                    target_type="VEHICLE",
                    target_id=str(saved.id),
                    new_values={
                        "customer_id": customer_id,
                        "customer_code": customer.customer_code,
                        "normalized_plate": saved.normalized_plate,
                        "display_plate": saved.display_plate,
                        "vehicle_type": saved.vehicle_type.value,
                    },
                )
            )
            return saved

    def update_vehicle(
        self,
        actor: User,
        vehicle_id: int,
        raw_plate: str,
        vehicle_type: VehicleType,
        note: str | None = None,
    ) -> Vehicle:
        """Update vehicle details."""
        self._require_admin(actor)
        norm_plate = normalize_plate(raw_plate)
        validate_normalized_plate(norm_plate)

        with self.session_manager.session() as session:
            veh_repo = SqlAlchemyVehicleRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            vehicle = veh_repo.get_by_id(vehicle_id)
            if vehicle is None:
                raise VehicleNotFoundError(f"Không tìm thấy phương tiện với ID {vehicle_id}.")

            existing = veh_repo.get_by_normalized_plate(norm_plate)
            if existing is not None and existing.id != vehicle_id:
                raise DuplicatePlateError(
                    f"Biển số '{norm_plate}' đã được đăng ký cho phương tiện khác."
                )

            old_values = {
                "normalized_plate": vehicle.normalized_plate,
                "display_plate": vehicle.display_plate,
                "vehicle_type": vehicle.vehicle_type.value,
                "note": vehicle.note,
            }

            vehicle.normalized_plate = norm_plate
            vehicle.display_plate = raw_plate.strip().upper()
            vehicle.vehicle_type = vehicle_type
            vehicle.note = note.strip() if note else None
            saved = veh_repo.save(vehicle)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.UPDATE_VEHICLE,
                    target_type="VEHICLE",
                    target_id=str(saved.id),
                    old_values=old_values,
                    new_values={
                        "normalized_plate": saved.normalized_plate,
                        "display_plate": saved.display_plate,
                        "vehicle_type": saved.vehicle_type.value,
                        "note": saved.note,
                    },
                )
            )
            return saved

    def delete_vehicle(
        self,
        actor: User,
        vehicle_id: int,
        reason: str | None = None,
    ) -> bool:
        """Delete a vehicle registration."""
        with self.session_manager.session() as session:
            veh_repo = SqlAlchemyVehicleRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            vehicle = veh_repo.get_by_id(vehicle_id)
            if vehicle is None:
                raise VehicleNotFoundError(f"Không tìm thấy phương tiện với ID {vehicle_id}.")

            deleted = veh_repo.delete(vehicle_id)
            if deleted:
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=actor.id,
                        username=actor.username,
                        action=AuditAction.DELETE_VEHICLE,
                        target_type="VEHICLE",
                        target_id=str(vehicle_id),
                        old_values={
                            "customer_id": vehicle.customer_id,
                            "normalized_plate": vehicle.normalized_plate,
                        },
                        reason=reason,
                    )
                )
            return deleted

    def find_by_plate(self, raw_plate: str) -> tuple[Vehicle | None, Customer | None]:
        """Look up registered vehicle and owner by license plate."""
        norm_plate = normalize_plate(raw_plate)
        if not norm_plate:
            return None, None

        with self.session_manager.session() as session:
            veh_repo = SqlAlchemyVehicleRepository(session)
            cust_repo = SqlAlchemyCustomerRepository(session)

            vehicle = veh_repo.get_by_normalized_plate(norm_plate)
            if vehicle is None:
                return None, None
            customer = cust_repo.get_by_id(vehicle.customer_id)
            return vehicle, customer

    def search_customers(self, query: str = "", limit: int = 50) -> list[Customer]:
        """Search customers by code, name, or phone number."""
        with self.session_manager.session() as session:
            cust_repo = SqlAlchemyCustomerRepository(session)
            return cust_repo.search(query, limit=limit)

    def get_customer(self, customer_id: int) -> Customer | None:
        """Fetch customer by ID with associated vehicles."""
        with self.session_manager.session() as session:
            cust_repo = SqlAlchemyCustomerRepository(session)
            return cust_repo.get_by_id(customer_id)

    @staticmethod
    def _require_admin(actor: User) -> None:
        if actor.status != UserStatus.ACTIVE or actor.role != UserRole.ADMIN:
            raise PermissionDeniedError("Chỉ Quản trị viên đang hoạt động được sửa hồ sơ.")
