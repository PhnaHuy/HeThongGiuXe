"""Domain enumerations for parking management system."""

from enum import StrEnum


class UserRole(StrEnum):
    """System user roles."""

    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    STAFF = "STAFF"

    @property
    def display_name(self) -> str:
        names = {
            UserRole.ADMIN: "Quản trị viên",
            UserRole.MANAGER: "Quản lý",
            UserRole.STAFF: "Nhân viên",
        }
        return names.get(self, self.value)


class UserStatus(StrEnum):
    """Account status."""

    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"

    @property
    def display_name(self) -> str:
        names = {
            UserStatus.ACTIVE: "Đang hoạt động",
            UserStatus.LOCKED: "Đã khóa",
        }
        return names.get(self, self.value)


class VehicleType(StrEnum):
    """Supported vehicle categories."""

    MOTORCYCLE = "MOTORCYCLE"
    CAR = "CAR"

    @property
    def display_name(self) -> str:
        names = {
            VehicleType.MOTORCYCLE: "Xe máy",
            VehicleType.CAR: "Ô tô",
        }
        return names.get(self, self.value)


class ParkingStatus(StrEnum):
    """Lifecycle states of a parking session."""

    DANG_GUI = "DANG_GUI"
    DA_RA = "DA_RA"

    @property
    def display_name(self) -> str:
        names = {
            ParkingStatus.DANG_GUI: "Đang gửi",
            ParkingStatus.DA_RA: "Đã ra",
        }
        return names.get(self, self.value)


class AuditAction(StrEnum):
    """Audit event action types."""

    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    LOGIN_FAILED = "LOGIN_FAILED"
    CREATE_USER = "CREATE_USER"
    UPDATE_USER = "UPDATE_USER"
    LOCK_USER = "LOCK_USER"
    UNLOCK_USER = "UNLOCK_USER"
    CREATE_CUSTOMER = "CREATE_CUSTOMER"
    UPDATE_CUSTOMER = "UPDATE_CUSTOMER"
    REGISTER_VEHICLE = "REGISTER_VEHICLE"
    UPDATE_VEHICLE = "UPDATE_VEHICLE"
    DELETE_VEHICLE = "DELETE_VEHICLE"
    CONFIRM_ENTRY = "CONFIRM_ENTRY"
    CONFIRM_EXIT = "CONFIRM_EXIT"
    FLAG_SESSION = "FLAG_SESSION"
    RESOLVE_SESSION = "RESOLVE_SESSION"
    RESOLVE_EXCEPTION = "RESOLVE_EXCEPTION"
    DELETE_SESSION = "DELETE_SESSION"
    UPDATE_SESSION = "UPDATE_SESSION"
    RECORD_EXCEPTION = "RECORD_EXCEPTION"
    CONFIGURE_CAPACITY = "CONFIGURE_CAPACITY"
    CONFIGURE_SOURCE = "CONFIGURE_SOURCE"


class EvidenceType(StrEnum):
    """Kinds of photographic evidence captured per session."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    PLATE_CROP = "PLATE_CROP"

    @property
    def display_name(self) -> str:
        names = {
            EvidenceType.ENTRY: "Ảnh lúc vào",
            EvidenceType.EXIT: "Ảnh lúc ra",
            EvidenceType.PLATE_CROP: "Ảnh cắt biển số",
        }
        return names.get(self, self.value)
