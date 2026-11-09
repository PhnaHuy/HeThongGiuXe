"""Parking Session lifecycle application service (M06, M07, M08, M10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from parking_app.domain.enums import (
    AuditAction,
    EvidenceType,
    ParkingStatus,
    UserRole,
    VehicleType,
)
from parking_app.domain.exceptions import (
    DuplicateActiveSessionError,
    PermissionDeniedError,
    SessionAlreadyClosedError,
    SessionNotFoundError,
    ValidationError,
)
from parking_app.domain.models import (
    AuditEntry,
    CapacitySummary,
    Evidence,
    ParkingSession,
    ParkingStatistics,
    User,
    UserStatus,
    Vehicle,
)
from parking_app.domain.plate import (
    normalize_plate,
    validate_normalized_plate,
)
from parking_app.domain.video import SourceKind
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.orm_models import ParkingCapacityModel
from parking_app.infrastructure.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyEvidenceRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyVehicleRepository,
)


class ParkingService:
    """Manages parking entries, exits, capacity monitoring, and photographic proof."""

    def __init__(
        self,
        session_manager: DatabaseSessionManager,
        evidence_storage: EvidenceStorage,
        motorcycle_capacity: int = 50,
        car_capacity: int = 20,
    ) -> None:
        self.session_manager = session_manager
        self.evidence_storage = evidence_storage
        self.motorcycle_capacity = motorcycle_capacity
        self.car_capacity = car_capacity
        self.operation_source_kind = SourceKind.LIVE
        with self.session_manager.session() as session:
            config = session.get(ParkingCapacityModel, 1)
            if config is not None:
                self.motorcycle_capacity = config.motorcycle_capacity
                self.car_capacity = config.car_capacity
        if self.motorcycle_capacity < 0 or self.car_capacity < 0:
            raise ValidationError("Cấu hình sức chứa hiện tại không được âm.")

    def update_capacity(
        self,
        actor: User,
        motorcycle_capacity: int,
        car_capacity: int,
    ) -> None:
        """Persist parking capacity by vehicle type (QT-04, M07)."""
        if actor.status != UserStatus.ACTIVE or not actor.is_admin:
            raise PermissionDeniedError("Chỉ Quản trị viên đang hoạt động được cấu hình sức chứa.")
        values = (motorcycle_capacity, car_capacity)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValidationError("Sức chứa phải là số nguyên không âm.")

        with self.session_manager.session() as session:
            config = session.get(ParkingCapacityModel, 1)
            old_values = {
                "motorcycle": config.motorcycle_capacity if config else self.motorcycle_capacity,
                "car": config.car_capacity if config else self.car_capacity,
            }
            if config is None:
                config = ParkingCapacityModel(
                    id=1,
                    motorcycle_capacity=motorcycle_capacity,
                    car_capacity=car_capacity,
                )
                session.add(config)
            else:
                config.motorcycle_capacity = motorcycle_capacity
                config.car_capacity = car_capacity
                config.updated_at = datetime.now(UTC)
            SqlAlchemyAuditRepository(session).add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.CONFIGURE_CAPACITY,
                    target_type="PARKING_CAPACITY",
                    target_id="1",
                    old_values=old_values,
                    new_values={"motorcycle": motorcycle_capacity, "car": car_capacity},
                )
            )
        self.motorcycle_capacity = motorcycle_capacity
        self.car_capacity = car_capacity

    def set_operation_source(self, kind: SourceKind) -> None:
        self.operation_source_kind = SourceKind(kind)

    def _require_operational_source(self, source_kind: SourceKind | None = None) -> None:
        effective_source = source_kind if source_kind is not None else self.operation_source_kind
        if effective_source not in (SourceKind.LIVE, SourceKind.MP4):
            raise ValidationError("Nguồn hình không được hỗ trợ để xác nhận lượt xe.")

    def get_capacity_summary(self) -> CapacitySummary:
        """Compute live occupancy against configured capacities."""
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            moto_active = repo.count_active(VehicleType.MOTORCYCLE)
            car_active = repo.count_active(VehicleType.CAR)

        total_cap = self.motorcycle_capacity + self.car_capacity
        total_act = moto_active + car_active
        moto_rem = max(0, self.motorcycle_capacity - moto_active)
        car_rem = max(0, self.car_capacity - car_active)
        total_rem = max(0, total_cap - total_act)

        return CapacitySummary(
            motorcycle_capacity=self.motorcycle_capacity,
            motorcycle_active=moto_active,
            car_capacity=self.car_capacity,
            car_active=car_active,
            total_capacity=total_cap,
            total_active=total_act,
            motorcycle_remaining=moto_rem,
            car_remaining=car_rem,
            total_remaining=total_rem,
            is_motorcycle_full=moto_active >= self.motorcycle_capacity,
            is_car_full=car_active >= self.car_capacity,
            is_full=total_act >= total_cap,
        )

    def get_statistics(
        self,
        actor: User,
        from_time: datetime | None = None,
        before_time: datetime | None = None,
    ) -> ParkingStatistics:
        """Return period entry/exit counts for managers and administrators (QL-03)."""
        if actor.status != UserStatus.ACTIVE or not actor.is_manager:
            raise PermissionDeniedError("Chỉ Quản lý hoặc Quản trị viên được xem thống kê.")
        if from_time is not None and before_time is not None and from_time >= before_time:
            raise ValidationError("Khoảng thời gian thống kê không hợp lệ.")
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            return ParkingStatistics(
                motorcycle_entries=repo.count_entries(
                    VehicleType.MOTORCYCLE, from_time, before_time
                ),
                motorcycle_exits=repo.count_exits(VehicleType.MOTORCYCLE, from_time, before_time),
                car_entries=repo.count_entries(VehicleType.CAR, from_time, before_time),
                car_exits=repo.count_exits(VehicleType.CAR, from_time, before_time),
            )

    def get_activity_report(
        self,
        actor: User,
        from_time: datetime | None = None,
        before_time: datetime | None = None,
    ) -> list[ParkingSession]:
        """List sessions with an entry or exit in the requested period."""
        if actor.status != UserStatus.ACTIVE or not actor.is_manager:
            raise PermissionDeniedError("Chỉ Quản lý hoặc Quản trị viên được xem thống kê.")
        if from_time is not None and before_time is not None and from_time >= before_time:
            raise ValidationError("Khoảng thời gian thống kê không hợp lệ.")
        with self.session_manager.session() as session:
            return SqlAlchemySessionRepository(session).sessions_with_activity(
                from_time, before_time
            )

    def create_entry(
        self,
        actor: User,
        raw_plate: str | None,
        vehicle_type: VehicleType,
        image_data: bytes | Any | None = None,
        note: str | None = None,
        attention_reason: str | None = None,
        source_kind: SourceKind | None = None,
        ocr_raw_text: str | None = None,
        ocr_proposed_plate: str | None = None,
        ocr_confidence: float | None = None,
        plate_image_data: bytes | None = None,
        proposed_vehicle_type: VehicleType | None = None,
    ) -> ParkingSession:
        """Create a new active parking stay (NV-05, NV-06)."""
        self._require_active_actor(actor, source_kind)
        self._require_operational_source(source_kind)
        if ocr_confidence is not None and not 0 <= ocr_confidence <= 1:
            raise ValidationError("Độ tin cậy OCR phải nằm trong khoảng 0–1.")

        # Plate normalization and unreadable fallback
        has_plate = bool(raw_plate and raw_plate.strip())
        now = datetime.now(UTC)
        time_token = now.strftime("%Y%m%d_%H%M%S")
        unique_token = uuid.uuid4().hex[:6].upper()
        session_code = f"SES-{time_token}-{unique_token}"

        if has_plate:
            norm_plate = normalize_plate(raw_plate)
            validate_normalized_plate(norm_plate)
            display_plate = raw_plate.strip().upper()
        else:
            # NV-06 / NV-09: Lượt không đọc được biển số có mã riêng để đối chiếu
            norm_plate = f"UNREADABLE_{unique_token}"
            display_plate = "CHƯA ĐỌC ĐƯỢC BIỂN"

        # Check for duplicate open sessions for the same normalized plate
        if has_plate:
            with self.session_manager.session() as session:
                sess_repo = SqlAlchemySessionRepository(session)
                existing = sess_repo.get_active_by_plate(norm_plate)
                if existing is not None:
                    entry_time = existing.entry_time.strftime("%H:%M %d/%m/%Y")
                    raise DuplicateActiveSessionError(
                        f"Xe biển số '{norm_plate}' hiện đang có một lượt gửi đang mở "
                        f"(Mã lượt: {existing.session_code}, vào lúc: {entry_time}). "
                        f"Không thể tạo thêm lượt đang mở cho cùng biển số."
                    )

        # Check customer and vehicle registry
        customer_id: int | None = None
        vehicle_id: int | None = None
        is_registered = False
        registered_vehicle: Vehicle | None = None

        if has_plate:
            with self.session_manager.session() as session:
                veh_repo = SqlAlchemyVehicleRepository(session)
                registered_vehicle = veh_repo.get_by_normalized_plate(norm_plate)
                if registered_vehicle is not None:
                    vehicle_id = registered_vehicle.id
                    customer_id = registered_vehicle.customer_id
                    is_registered = True

        clean_attention_reason = attention_reason.strip() if attention_reason else None
        image_path: str | None = None
        plate_image_path: str | None = None

        try:
            if image_data is not None:
                image_path = self.evidence_storage.save_image(
                    image_data=image_data,
                    session_code=session_code,
                    evidence_type=EvidenceType.ENTRY,
                )
            if plate_image_data is not None:
                plate_image_path = self.evidence_storage.save_image(
                    image_data=plate_image_data,
                    session_code=session_code,
                    evidence_type=EvidenceType.PLATE_CROP,
                )
            with self.session_manager.session() as session:
                sess_repo = SqlAlchemySessionRepository(session)
                ev_repo = SqlAlchemyEvidenceRepository(session)
                audit_repo = SqlAlchemyAuditRepository(session)

                parking_session = ParkingSession(
                    id=None,
                    session_code=session_code,
                    vehicle_id=vehicle_id,
                    customer_id=customer_id,
                    snapshot_plate=norm_plate,
                    snapshot_display_plate=display_plate,
                    snapshot_vehicle_type=vehicle_type,
                    is_registered_customer=is_registered,
                    entry_time=now,
                    exit_time=None,
                    status=ParkingStatus.DANG_GUI,
                    needs_attention=bool(clean_attention_reason),
                    attention_reason=clean_attention_reason,
                    entry_operator_id=actor.id,
                    entry_image_path=image_path,
                    note=note.strip() if note else None,
                )
                saved = sess_repo.save(parking_session)

                if image_path:
                    ev_repo.add(
                        Evidence(
                            id=None,
                            session_id=saved.id,
                            evidence_type=EvidenceType.ENTRY,
                            file_path=image_path,
                            created_at=now,
                        )
                    )
                if plate_image_path:
                    ev_repo.add(
                        Evidence(
                            id=None,
                            session_id=saved.id,
                            evidence_type=EvidenceType.PLATE_CROP,
                            file_path=plate_image_path,
                            created_at=now,
                        )
                    )

                new_values: dict[str, Any] = {
                    "plate": saved.snapshot_plate,
                    "type": saved.snapshot_vehicle_type.value,
                    "is_registered": saved.is_registered_customer,
                    "registered_vehicle_type": (
                        registered_vehicle.vehicle_type.value if registered_vehicle else None
                    ),
                    "needs_attention": saved.needs_attention,
                    "attention_reason": saved.attention_reason,
                    "entry_time": saved.entry_time.isoformat(),
                    "entry_image_path": saved.entry_image_path,
                }
                if proposed_vehicle_type is not None:
                    new_values["proposed_vehicle_type"] = proposed_vehicle_type.value
                    if proposed_vehicle_type != vehicle_type:
                        new_values["vehicle_type_correction"] = {
                            "before": proposed_vehicle_type.value,
                            "after": vehicle_type.value,
                        }
                if ocr_raw_text is not None or ocr_proposed_plate is not None:
                    new_values["plate_ocr"] = {
                        "raw_text": ocr_raw_text,
                        "proposed_plate": ocr_proposed_plate,
                        "confidence": ocr_confidence,
                        "confirmed_plate": norm_plate if has_plate else None,
                        "plate_image_path": plate_image_path,
                    }
                    if (
                        ocr_proposed_plate
                        and has_plate
                        and normalize_plate(ocr_proposed_plate) != norm_plate
                    ):
                        new_values["plate_correction"] = {
                            "before": normalize_plate(ocr_proposed_plate),
                            "after": norm_plate,
                        }
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=actor.id,
                        username=actor.username,
                        action=AuditAction.CONFIRM_ENTRY,
                        target_type="PARKING_SESSION",
                        target_id=saved.session_code,
                        new_values=new_values,
                    )
                )
                return saved
        except IntegrityError as exc:
            self.evidence_storage.remove_file(image_path)
            self.evidence_storage.remove_file(plate_image_path)
            if has_plate:
                active_session = self.find_active_by_plate(norm_plate)
                if active_session is not None:
                    raise DuplicateActiveSessionError(
                        f"Xe biển số '{norm_plate}' hiện đang có lượt gửi "
                        f"'{active_session.session_code}' đang mở."
                    ) from exc
            raise
        except Exception:
            # Transaction failed: clean up orphaned file
            self.evidence_storage.remove_file(image_path)
            self.evidence_storage.remove_file(plate_image_path)
            raise

    def close_exit(
        self,
        actor: User,
        session_id_or_code: int | str,
        image_data: bytes | Any | None = None,
        note: str | None = None,
        source_kind: SourceKind | None = None,
        ocr_raw_text: str | None = None,
        ocr_proposed_plate: str | None = None,
        ocr_confidence: float | None = None,
        plate_image_data: bytes | None = None,
        proposed_vehicle_type: VehicleType | None = None,
    ) -> ParkingSession:
        """Close an active parking session (NV-07)."""
        self._require_active_actor(actor, source_kind)
        self._require_operational_source(source_kind)
        if ocr_confidence is not None and not 0 <= ocr_confidence <= 1:
            raise ValidationError("Độ tin cậy OCR phải nằm trong khoảng 0–1.")
        now = datetime.now(UTC)

        with self.session_manager.session() as session:
            sess_repo = SqlAlchemySessionRepository(session)
            if isinstance(session_id_or_code, int):
                target = sess_repo.get_by_id(session_id_or_code)
            else:
                target = sess_repo.get_by_code(str(session_id_or_code))

            if target is None:
                raise SessionNotFoundError(
                    f"Không tìm thấy lượt gửi xe với định danh '{session_id_or_code}'."
                )

            # Invariant: Cannot close a session twice!
            if target.is_closed:
                exit_time = (
                    target.exit_time.strftime("%H:%M %d/%m/%Y") if target.exit_time else "đã đóng"
                )
                raise SessionAlreadyClosedError(
                    f"Lượt gửi xe '{target.session_code}' đã được đóng trước đó "
                    f"(lúc {exit_time}). "
                    f"Không thể đóng lượt lần thứ hai."
                )

            session_code = target.session_code
            session_id = target.id

        # Save exit photographic evidence
        image_path: str | None = None
        plate_image_path: str | None = None

        try:
            if image_data is not None:
                image_path = self.evidence_storage.save_image(
                    image_data=image_data,
                    session_code=session_code,
                    evidence_type=EvidenceType.EXIT,
                )
            if plate_image_data is not None:
                plate_image_path = self.evidence_storage.save_image(
                    image_data=plate_image_data,
                    session_code=session_code,
                    evidence_type=EvidenceType.PLATE_CROP,
                )
            with self.session_manager.session() as session:
                sess_repo = SqlAlchemySessionRepository(session)
                ev_repo = SqlAlchemyEvidenceRepository(session)
                audit_repo = SqlAlchemyAuditRepository(session)

                target = sess_repo.get_by_id(session_id)
                if target is None or target.is_closed:
                    raise SessionAlreadyClosedError("Lượt xe đã bị đóng bởi phiên làm việc khác.")

                target.exit_time = now
                target.status = ParkingStatus.DA_RA
                target.exit_operator_id = actor.id
                target.exit_image_path = image_path
                if note:
                    target.note = f"{target.note or ''}\n[Ra]: {note}".strip()

                saved = sess_repo.save(target)

                if image_path:
                    ev_repo.add(
                        Evidence(
                            id=None,
                            session_id=saved.id,
                            evidence_type=EvidenceType.EXIT,
                            file_path=image_path,
                            created_at=now,
                        )
                    )
                if plate_image_path:
                    ev_repo.add(
                        Evidence(
                            id=None,
                            session_id=saved.id,
                            evidence_type=EvidenceType.PLATE_CROP,
                            file_path=plate_image_path,
                            created_at=now,
                        )
                    )

                new_values: dict[str, Any] = {
                    "status": saved.status.value,
                    "exit_time": saved.exit_time.isoformat(),
                    "entry_image_path": saved.entry_image_path,
                    "exit_image_path": saved.exit_image_path,
                }
                if ocr_raw_text is not None or ocr_proposed_plate is not None:
                    new_values["plate_ocr"] = {
                        "raw_text": ocr_raw_text,
                        "proposed_plate": ocr_proposed_plate,
                        "confidence": ocr_confidence,
                        "matched_session_plate": target.snapshot_plate,
                        "plate_image_path": plate_image_path,
                    }
                if proposed_vehicle_type is not None:
                    new_values["vehicle_type_review"] = {
                        "proposed": proposed_vehicle_type.value,
                        "matched_session": target.snapshot_vehicle_type.value,
                        "mismatch": proposed_vehicle_type != target.snapshot_vehicle_type,
                    }
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=actor.id,
                        username=actor.username,
                        action=AuditAction.CONFIRM_EXIT,
                        target_type="PARKING_SESSION",
                        target_id=saved.session_code,
                        old_values={"status": ParkingStatus.DANG_GUI.value},
                        new_values=new_values,
                    )
                )
                return saved
        except Exception:
            self.evidence_storage.remove_file(image_path)
            self.evidence_storage.remove_file(plate_image_path)
            raise

    def flag_session_attention(
        self,
        actor: User,
        session_id: int,
        reason: str,
    ) -> ParkingSession:
        """Mark a session as needing attention without closing it (NV-09, NV-10)."""
        self._require_active_actor(actor, SourceKind.LIVE)
        self._require_operational_source()
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Lý do đánh dấu cần xử lý không được để trống.")

        with self.session_manager.session() as session:
            sess_repo = SqlAlchemySessionRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            target = sess_repo.get_by_id(session_id)
            if target is None:
                raise SessionNotFoundError(f"Không tìm thấy lượt gửi ID {session_id}.")

            target.needs_attention = True
            target.attention_reason = clean_reason
            saved = sess_repo.save(target)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.FLAG_SESSION,
                    target_type="PARKING_SESSION",
                    target_id=saved.session_code,
                    new_values={"needs_attention": True, "reason": clean_reason},
                    reason=clean_reason,
                )
            )
            return saved

    def delete_active_session(self, actor: User, session_id: int) -> None:
        """Delete an active session and record the administrator's action."""
        if actor.status != UserStatus.ACTIVE or not actor.is_admin:
            raise PermissionDeniedError("Chỉ quản trị viên đang hoạt động được xóa lượt gửi xe.")
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            target = repo.get_by_id(session_id)
            if target is None:
                raise SessionNotFoundError(f"Không tìm thấy lượt gửi ID {session_id}.")
            if target.status != ParkingStatus.DANG_GUI or not repo.delete_active(session_id):
                raise ValidationError("Chỉ có thể xóa lượt xe đang gửi.")
            SqlAlchemyAuditRepository(session).add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.DELETE_SESSION,
                    target_type="PARKING_SESSION",
                    target_id=target.session_code,
                    old_values={
                        "plate": target.snapshot_display_plate,
                        "vehicle_type": target.snapshot_vehicle_type.value,
                        "entry_time": target.entry_time.isoformat(),
                    },
                    new_values=None,
                )
            )

    def resolve_session_attention(
        self,
        actor: User,
        session_id_or_code: int | str,
        reason: str,
    ) -> ParkingSession:
        """Resolve an operator-flagged session while preserving the audit trail (QL-04)."""
        if actor.status != UserStatus.ACTIVE or not actor.is_manager:
            raise PermissionDeniedError("Chỉ Quản lý hoặc Quản trị viên được xử lý ngoại lệ.")
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Cần ghi lý do xử lý ngoại lệ.")
        with self.session_manager.session() as session:
            sess_repo = SqlAlchemySessionRepository(session)
            target = (
                sess_repo.get_by_id(session_id_or_code)
                if isinstance(session_id_or_code, int)
                else sess_repo.get_by_code(str(session_id_or_code))
            )
            if target is None:
                raise SessionNotFoundError(f"Không tìm thấy lượt gửi '{session_id_or_code}'.")
            if not target.needs_attention:
                raise ValidationError("Lượt này không còn ở trạng thái cần xử lý.")
            old_values = {
                "needs_attention": True,
                "attention_reason": target.attention_reason,
            }
            target.needs_attention = False
            target.attention_reason = None
            saved = sess_repo.save(target)
            SqlAlchemyAuditRepository(session).add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.RESOLVE_SESSION,
                    target_type="PARKING_SESSION",
                    target_id=saved.session_code,
                    old_values=old_values,
                    new_values={"needs_attention": False},
                    reason=clean_reason,
                )
            )
            return saved

    def update_session_snapshot(
        self,
        actor: User,
        session_id: int,
        new_plate: str | None = None,
        new_vehicle_type: VehicleType | None = None,
        reason: str | None = None,
    ) -> ParkingSession:
        """Correct OCR or vehicle type on an active session with full audit (NV-08).

        Invariant: Modifying snapshot on a session does NOT mutate the vehicle registry.
        """
        self._require_active_actor(actor, SourceKind.LIVE)
        clean_reason = reason.strip() if reason else "Chỉnh sửa kết quả nhận dạng"

        with self.session_manager.session() as session:
            sess_repo = SqlAlchemySessionRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            target = sess_repo.get_by_id(session_id)
            if target is None:
                raise SessionNotFoundError(f"Không tìm thấy lượt gửi ID {session_id}.")
            if target.is_closed:
                raise ValidationError(
                    "Không thể chỉnh sửa thông tin nhận dạng của lượt đã kết thúc."
                )
            if not new_plate and new_vehicle_type is None:
                raise ValidationError("Cần cung cấp biển số hoặc loại xe cần điều chỉnh.")

            old_values = {
                "snapshot_plate": target.snapshot_plate,
                "snapshot_display_plate": target.snapshot_display_plate,
                "snapshot_vehicle_type": target.snapshot_vehicle_type.value,
            }

            if new_plate:
                norm = normalize_plate(new_plate)
                validate_normalized_plate(norm)
                # Check duplicate active session if changing plate
                if norm != target.snapshot_plate:
                    other_active = sess_repo.get_active_by_plate(norm)
                    if other_active is not None and other_active.id != target.id:
                        raise DuplicateActiveSessionError(
                            f"Biển số '{norm}' hiện đã có một lượt gửi đang mở khác."
                        )
                target.snapshot_plate = norm
                target.snapshot_display_plate = new_plate.strip().upper()

            if new_vehicle_type:
                target.snapshot_vehicle_type = new_vehicle_type

            saved = sess_repo.save(target)

            audit_repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.UPDATE_SESSION,
                    target_type="PARKING_SESSION",
                    target_id=saved.session_code,
                    old_values=old_values,
                    new_values={
                        "snapshot_plate": saved.snapshot_plate,
                        "snapshot_display_plate": saved.snapshot_display_plate,
                        "snapshot_vehicle_type": saved.snapshot_vehicle_type.value,
                        "entry_image_path": saved.entry_image_path,
                    },
                    reason=clean_reason,
                )
            )
            return saved

    def find_active_by_plate(self, raw_plate: str) -> ParkingSession | None:
        """Look up currently open parking session by license plate."""
        norm = normalize_plate(raw_plate)
        if not norm:
            return None
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            return repo.get_active_by_plate(norm)

    def list_active_sessions(self, limit: int = 100) -> list[ParkingSession]:
        """List currently parked vehicles."""
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            return repo.list_active(limit=limit)

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
        """Search historical and active sessions with filters (NV-11)."""
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            return repo.search_sessions(
                plate_query=plate_query,
                customer_query=customer_query,
                status=status,
                vehicle_type=vehicle_type,
                needs_attention_only=needs_attention_only,
                entry_from=entry_from,
                entry_before=entry_before,
                limit=limit,
            )

    def find_registered_vehicle(self, raw_plate: str) -> Vehicle | None:
        """Find a registered vehicle by a partially or fully entered plate."""
        normalized = normalize_plate(raw_plate)
        if not normalized:
            return None
        with self.session_manager.session() as session:
            repo = SqlAlchemyVehicleRepository(session)
            return repo.get_by_normalized_plate(normalized)

    def record_unmatched_exit(
        self,
        actor: User,
        reason: str,
        plate_query: str = "",
        customer_query: str = "",
        vehicle_type: VehicleType | None = None,
        entry_from: datetime | None = None,
        entry_before: datetime | None = None,
        image_data: bytes | Any | None = None,
    ) -> str:
        """Record a reviewed exit that could not be matched to an open session."""
        self._require_active_actor(actor, SourceKind.LIVE)
        self._require_operational_source()
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Lý do cần xử lý không được để trống.")

        incident_code = f"EXIT-UNMATCHED-{uuid.uuid4().hex[:12].upper()}"
        image_path = None
        if image_data is not None:
            image_path = self.evidence_storage.save_image(
                image_data=image_data,
                session_code=incident_code,
                evidence_type=EvidenceType.EXIT,
            )
        try:
            with self.session_manager.session() as session:
                audit_repo = SqlAlchemyAuditRepository(session)
                audit_repo.add(
                    AuditEntry(
                        id=None,
                        user_id=actor.id,
                        username=actor.username,
                        action=AuditAction.RECORD_EXCEPTION,
                        target_type="UNMATCHED_EXIT",
                        target_id=incident_code,
                        new_values={
                            "plate_query": plate_query.strip(),
                            "customer_query": customer_query.strip(),
                            "vehicle_type": vehicle_type.value if vehicle_type else None,
                            "entry_from": entry_from.isoformat() if entry_from else None,
                            "entry_before": entry_before.isoformat() if entry_before else None,
                            "evidence_path": image_path,
                            "recorded_at": datetime.now(UTC).isoformat(),
                        },
                        reason=clean_reason,
                    )
                )
        except Exception:
            self.evidence_storage.remove_file(image_path)
            raise
        return incident_code

    def get_session(self, session_id: int) -> ParkingSession | None:
        """Fetch session by primary key ID."""
        with self.session_manager.session() as session:
            repo = SqlAlchemySessionRepository(session)
            return repo.get_by_id(session_id)

    def _require_active_actor(self, actor: User, source_kind: SourceKind | None = None) -> None:
        if actor.status != UserStatus.ACTIVE:
            raise PermissionDeniedError(
                "Tài khoản không hoạt động không được phép xác nhận lượt xe."
            )
        effective_source = source_kind if source_kind is not None else self.operation_source_kind
        if actor.role != UserRole.STAFF and not (
            actor.role == UserRole.ADMIN and effective_source == SourceKind.MP4
        ):
            raise PermissionDeniedError(
                "Chỉ nhân viên bãi xe được phép xác nhận hoặc xử lý lượt xe."
            )
