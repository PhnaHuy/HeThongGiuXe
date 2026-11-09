"""Audit inquiry and tracking application service."""

from __future__ import annotations

from datetime import datetime

from parking_app.domain.enums import AuditAction, UserStatus
from parking_app.domain.exceptions import PermissionDeniedError, ValidationError
from parking_app.domain.models import AuditEntry, ExceptionCase, User
from parking_app.domain.plate import normalize_plate
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import SqlAlchemyAuditRepository


class AuditService:
    """Provides querying access to system audit records."""

    def __init__(self, session_manager: DatabaseSessionManager) -> None:
        self.session_manager = session_manager

    def list_recent_audits(
        self,
        actor: User,
        limit: int = 100,
        user_id: int | None = None,
        action: AuditAction | None = None,
        from_time: datetime | None = None,
        before_time: datetime | None = None,
    ) -> list[AuditEntry]:
        """Fetch chronological audit records (Admin and Manager)."""
        self._require_manager(actor)
        if limit < 1:
            raise ValidationError("Giới hạn nhật ký phải lớn hơn 0.")
        if from_time is not None and before_time is not None and from_time >= before_time:
            raise ValidationError("Khoảng thời gian lọc nhật ký không hợp lệ.")
        with self.session_manager.session() as session:
            repo = SqlAlchemyAuditRepository(session)
            return repo.list_recent(
                limit=limit,
                user_id=user_id,
                action=action,
                from_time=from_time,
                before_time=before_time,
            )

    def list_exceptions(
        self,
        actor: User,
        handled: bool | None = None,
        limit: int = 1000,
    ) -> list[ExceptionCase]:
        """List auditable anomalies and their handling state (QL-04)."""
        self._require_manager(actor)
        if limit < 1:
            raise ValidationError("Giới hạn danh sách ngoại lệ phải lớn hơn 0.")
        with self.session_manager.session() as session:
            repo = SqlAlchemyAuditRepository(session)
            entries = repo.list_recent(limit=5000)

        resolutions: dict[tuple[AuditAction, str], datetime] = {}
        for entry in entries:
            if entry.action in (AuditAction.RESOLVE_SESSION, AuditAction.RESOLVE_EXCEPTION):
                key = (entry.action, entry.target_id or "")
                resolutions[key] = max(resolutions.get(key, entry.timestamp), entry.timestamp)

        cases: list[ExceptionCase] = []
        latest_session_anomalies: dict[str, AuditEntry] = {}
        for entry in entries:
            if entry.action == AuditAction.FLAG_SESSION:
                latest_session_anomalies.setdefault(entry.target_id or "", entry)
            elif entry.action == AuditAction.CONFIRM_ENTRY and (
                (entry.new_values or {}).get("needs_attention")
            ):
                latest_session_anomalies.setdefault(entry.target_id or "", entry)

        for session_code, entry in latest_session_anomalies.items():
            resolved_at = resolutions.get((AuditAction.RESOLVE_SESSION, session_code))
            handled_case = bool(resolved_at and resolved_at >= entry.timestamp)
            values = entry.new_values or {}
            plate_ocr = values.get("plate_ocr") or {}
            cases.append(
                ExceptionCase(
                    reference=f"SESSION:{session_code}",
                    category="Lượt cần xử lý",
                    description=values.get("reason")
                    or values.get("attention_reason")
                    or entry.reason
                    or "Nhân viên đánh dấu cần kiểm tra.",
                    plate=values.get("plate")
                    or plate_ocr.get("confirmed_plate")
                    or values.get("snapshot_plate")
                    or "",
                    operator=entry.username or "Không rõ",
                    timestamp=entry.timestamp,
                    evidence_path=plate_ocr.get("plate_image_path")
                    or values.get("entry_image_path"),
                    handled=handled_case,
                    session_code=session_code,
                )
            )

        for entry in entries:
            values = entry.new_values or {}
            if (
                entry.action == AuditAction.RECORD_EXCEPTION
                and entry.target_type == "UNMATCHED_EXIT"
            ):
                incident_id = entry.target_id or ""
                resolved_at = resolutions.get((AuditAction.RESOLVE_EXCEPTION, incident_id))
                cases.append(
                    ExceptionCase(
                        reference=incident_id,
                        category="Không tìm thấy lượt xe ra",
                        description=entry.reason or "Đã ghi nhận xe ra chưa khớp lượt.",
                        plate=values.get("plate_query", ""),
                        operator=entry.username or "Không rõ",
                        timestamp=entry.timestamp,
                        evidence_path=values.get("evidence_path"),
                        handled=bool(resolved_at and resolved_at >= entry.timestamp),
                    )
                )
            elif entry.action in (AuditAction.CONFIRM_ENTRY, AuditAction.CONFIRM_EXIT):
                plate_correction = values.get("plate_correction")
                type_correction = values.get("vehicle_type_correction")
                plate_review = values.get("plate_ocr") or {}
                type_review = values.get("vehicle_type_review") or {}
                plate_mismatch = (
                    entry.action == AuditAction.CONFIRM_EXIT
                    and plate_review.get("proposed_plate")
                    and plate_review.get("matched_session_plate")
                    and normalize_plate(plate_review["proposed_plate"])
                    != normalize_plate(plate_review["matched_session_plate"])
                )
                type_mismatch = bool(type_review.get("mismatch"))
                if not (plate_correction or type_correction or plate_mismatch or type_mismatch):
                    continue
                issue_parts = []
                if plate_correction or plate_mismatch:
                    issue_parts.append("Biển số OCR khác kết quả đối chiếu")
                if type_correction or type_mismatch:
                    issue_parts.append("Loại xe AI khác kết quả xác nhận")
                cases.append(
                    ExceptionCase(
                        reference=f"AUDIT:{entry.id}",
                        category=" / ".join(issue_parts),
                        description="; ".join(issue_parts) + ". Đã được nhân viên xác nhận.",
                        plate=plate_review.get("confirmed_plate")
                        or plate_review.get("matched_session_plate")
                        or (plate_correction or {}).get("after", ""),
                        operator=entry.username or "Không rõ",
                        timestamp=entry.timestamp,
                        evidence_path=plate_review.get("plate_image_path")
                        or values.get("exit_image_path")
                        or values.get("entry_image_path"),
                        handled=True,
                        session_code=entry.target_id,
                    )
                )
            elif entry.action == AuditAction.UPDATE_SESSION:
                old_values = entry.old_values or {}
                plate_changed = old_values.get("snapshot_plate") != values.get("snapshot_plate")
                type_changed = old_values.get("snapshot_vehicle_type") != values.get(
                    "snapshot_vehicle_type"
                )
                if not (plate_changed or type_changed):
                    continue
                changes = []
                if plate_changed:
                    changes.append(
                        f"Biển số {old_values.get('snapshot_plate', '')} "
                        f"→ {values.get('snapshot_plate', '')}"
                    )
                if type_changed:
                    changes.append(
                        f"Loại xe {old_values.get('snapshot_vehicle_type', '')} "
                        f"→ {values.get('snapshot_vehicle_type', '')}"
                    )
                cases.append(
                    ExceptionCase(
                        reference=f"AUDIT:{entry.id}",
                        category="Sửa nhận dạng thủ công",
                        description="; ".join(changes)
                        + (f". Lý do: {entry.reason}" if entry.reason else ""),
                        plate=values.get("snapshot_display_plate")
                        or values.get("snapshot_plate", ""),
                        operator=entry.username or "Không rõ",
                        timestamp=entry.timestamp,
                        evidence_path=values.get("entry_image_path"),
                        handled=True,
                        session_code=entry.target_id,
                    )
                )

        cases.sort(key=lambda case: case.timestamp, reverse=True)
        if handled is not None:
            cases = [case for case in cases if case.handled is handled]
        return cases[:limit]

    def resolve_exception(self, actor: User, incident_id: str, reason: str) -> AuditEntry:
        """Mark an unmatched-exit incident as reviewed without altering its original record."""
        self._require_manager(actor)
        clean_reason = reason.strip()
        if not clean_reason:
            raise ValidationError("Cần ghi lý do xử lý ngoại lệ.")
        with self.session_manager.session() as session:
            repo = SqlAlchemyAuditRepository(session)
            matching = next(
                (
                    entry
                    for entry in repo.list_recent(limit=5000, action=AuditAction.RECORD_EXCEPTION)
                    if entry.target_type == "UNMATCHED_EXIT" and entry.target_id == incident_id
                ),
                None,
            )
            if matching is None:
                raise ValidationError("Không tìm thấy ngoại lệ cần xử lý.")
            if any(
                entry.target_id == incident_id
                for entry in repo.list_recent(limit=5000, action=AuditAction.RESOLVE_EXCEPTION)
            ):
                raise ValidationError("Ngoại lệ này đã được xử lý trước đó.")
            return repo.add(
                AuditEntry(
                    id=None,
                    user_id=actor.id,
                    username=actor.username,
                    action=AuditAction.RESOLVE_EXCEPTION,
                    target_type="UNMATCHED_EXIT",
                    target_id=incident_id,
                    old_values={"handled": False},
                    new_values={"handled": True},
                    reason=clean_reason,
                )
            )

    @staticmethod
    def _require_manager(actor: User) -> None:
        if actor.status != UserStatus.ACTIVE or not actor.is_manager:
            raise PermissionDeniedError("Bạn không có quyền truy cập nhật ký kiểm toán.")
