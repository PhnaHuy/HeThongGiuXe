"""Domain and application exceptions."""


class DomainError(Exception):
    """Base exception for domain and business logic errors."""


class ValidationError(DomainError):
    """Raised when data fails domain validation rules."""


class AuthenticationError(DomainError):
    """Raised on invalid credentials or failed login."""


class AccountLockedError(DomainError):
    """Raised when an account is locked/inactive."""


class PermissionDeniedError(DomainError):
    """Raised when an action violates authorization policy."""


class EntityNotFoundError(DomainError):
    """Base exception when a requested entity does not exist."""


class UserNotFoundError(EntityNotFoundError):
    """User not found."""


class CustomerNotFoundError(EntityNotFoundError):
    """Customer not found."""


class VehicleNotFoundError(EntityNotFoundError):
    """Vehicle not found."""


class DuplicateEntityError(DomainError):
    """Base exception for unique constraint violations."""


class DuplicateUserError(DuplicateEntityError):
    """Username already taken."""


class DuplicateCustomerError(DuplicateEntityError):
    """Customer code or contact info already registered."""


class DuplicatePlateError(DuplicateEntityError):
    """Normalized license plate already registered to another vehicle."""


class DuplicateActiveSessionError(DomainError):
    """Raised when an active session already exists for the same normalized plate."""


class SessionAlreadyClosedError(DomainError):
    """Raised when attempting to close an already finished session."""


class SessionNotFoundError(EntityNotFoundError):
    """Parking session not found."""


class CapacityExceededError(DomainError):
    """Raised when parking capacity for a vehicle category is exhausted."""


class ImageStorageError(DomainError):
    """Raised when writing evidence image files fails."""
