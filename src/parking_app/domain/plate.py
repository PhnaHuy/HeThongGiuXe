"""License plate normalization and validation according to domain invariants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from parking_app.domain.exceptions import ValidationError

# Characters that are formatting separators in Vietnamese license plates
_SEPARATOR_PATTERN = re.compile(r"[\s\.\-_/\\:]+")
_ALPHANUMERIC_PATTERN = re.compile(r"^[A-Z0-9]+$")


@dataclass(frozen=True)
class PlateOCRObservation:
    raw_text: str
    confidence: float
    normalized_plate: str | None


@dataclass(frozen=True)
class PlateRecognition:
    observations: tuple[PlateOCRObservation, ...]
    proposed_plate: str | None
    confidence: float | None
    plate_image_data: bytes | None
    samples_considered: int

    @property
    def raw_text(self) -> str | None:
        texts = tuple(item.raw_text for item in self.observations if item.raw_text)
        return " | ".join(texts) or None


@dataclass(frozen=True)
class PlateRecognitionOptions:
    python_path: Path
    worker_path: Path
    cache_dir: Path
    timeout_s: float = 30.0
    max_samples: int = 5
    detector_model_path: Path | None = None
    detector_confidence: float = 0.15
    detector_image_size: int = 960
    detector_device: str = "cpu"
    max_regions: int = 2
    min_ocr_confidence: float = 0.6
    ocr_model_path: Path | None = None
    ocr_config_path: Path | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValidationError("Thời gian chờ OCR phải là số dương.")
        if not 1 <= self.max_samples <= 10:
            raise ValidationError("Số ảnh OCR phải nằm trong khoảng 1–10.")
        if not 1 <= self.max_regions <= 2:
            raise ValidationError("Số vùng biển trên mỗi ảnh phải nằm trong khoảng 1–2.")
        if not all(
            isfinite(value) and 0 < value <= 1
            for value in (self.detector_confidence, self.min_ocr_confidence)
        ):
            raise ValidationError("Ngưỡng nhận diện biển số phải nằm trong khoảng (0, 1].")
        if not 32 <= self.detector_image_size <= 2048 or not self.detector_device.strip():
            raise ValidationError("Kích thước hoặc thiết bị detector biển số không hợp lệ.")


def normalize_plate(raw_plate: str | None) -> str:
    """Safely normalize a license plate string for indexing and matching.

    Invariants:
    - Strips leading/trailing whitespace.
    - Converts all ASCII characters to uppercase.
    - Removes visual presentation separators (spaces, dots, dashes, slashes).
    - NEVER substitutes ambiguous characters like 0/O or 1/I (prohibited by business rule).
    - NEVER fabricates or injects characters to make a plate look 'valid'.
    """
    if not raw_plate:
        return ""
    cleaned = _SEPARATOR_PATTERN.sub("", raw_plate.strip()).upper()
    return cleaned


def validate_normalized_plate(normalized: str) -> None:
    """Validate a normalized plate meets minimum structural criteria.

    Raises ValidationError if invalid.
    """
    if not normalized:
        raise ValidationError("Biển số xe không được để trống.")
    if len(normalized) < 4:
        raise ValidationError(f"Biển số '{normalized}' quá ngắn (tối thiểu 4 ký tự).")
    if len(normalized) > 15:
        raise ValidationError(f"Biển số '{normalized}' quá dài (tối đa 15 ký tự).")
    if not _ALPHANUMERIC_PATTERN.match(normalized):
        raise ValidationError(
            f"Biển số '{normalized}' chứa ký tự không hợp lệ. Chỉ chấp nhận chữ cái và chữ số."
        )


def format_display_plate(raw_or_normalized: str) -> str:
    """Provide a clean display string preserving standard readable representation."""
    cleaned = normalize_plate(raw_or_normalized)
    if not cleaned:
        return ""
    # Standard 2-digit province prefix e.g. 51F12345 -> 51F-123.45 or 29A88888 -> 29A-888.88
    # Keep as normalized upper if formatting cannot be deduced safely
    return cleaned
