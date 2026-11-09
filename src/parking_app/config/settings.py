"""Application configuration, directory paths, and initial seed defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from parking_app.domain.enums import UserRole, UserStatus
from parking_app.domain.models import User
from parking_app.domain.plate import PlateRecognitionOptions
from parking_app.domain.video import VideoOptions, VisionOptions
from parking_app.infrastructure.persistence.database import DatabaseSessionManager
from parking_app.infrastructure.persistence.repositories import SqlAlchemyUserRepository
from parking_app.infrastructure.security import hash_password

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _vision_options() -> VisionOptions:
    model_path = Path(
        os.getenv("PARKING_VISION_MODEL", str(PROJECT_ROOT / "models" / "yolov8n.pt"))
    ).expanduser()
    if not model_path.is_absolute():
        model_path = PROJECT_ROOT / model_path
    return VisionOptions(
        model_path=model_path,
        confidence_threshold=float(os.getenv("PARKING_VISION_CONFIDENCE", "0.25")),
        image_size=int(os.getenv("PARKING_VISION_IMAGE_SIZE", "640")),
        device=os.getenv("PARKING_VISION_DEVICE", "cpu"),
        crossing_deadband=float(os.getenv("PARKING_CROSSING_DEADBAND", "0.015")),
        crossing_stable_frames=int(os.getenv("PARKING_CROSSING_STABLE_FRAMES", "2")),
        stale_track_frames=int(os.getenv("PARKING_TRACK_STALE_FRAMES", "300")),
    )


def _plate_recognition_options() -> PlateRecognitionOptions:
    backend = os.getenv("PARKING_OCR_BACKEND", "fast_plate")
    if backend not in {"fast_plate", "paddle"}:
        raise ValueError("PARKING_OCR_BACKEND phải là fast_plate hoặc paddle.")
    runtime = ".venv-alpr" if backend == "fast_plate" else ".venv-ocr-313"
    worker = "plate_ocr_worker.py" if backend == "fast_plate" else "ocr_worker.py"
    detector_path = Path(
        os.getenv("PARKING_PLATE_MODEL", str(PROJECT_ROOT / "models" / "license_plate_yolo11s.pt"))
    ).expanduser()
    python_path = Path(
        os.getenv(
            "PARKING_OCR_PYTHON",
            str(PROJECT_ROOT / runtime / "Scripts" / "python.exe"),
        )
    ).expanduser()
    worker_path = Path(
        os.getenv("PARKING_OCR_WORKER", str(PROJECT_ROOT / "scripts" / worker))
    ).expanduser()
    cache_dir = Path(
        os.getenv("PARKING_OCR_CACHE", str(PROJECT_ROOT / ".runtime" / "paddlex"))
    ).expanduser()
    return PlateRecognitionOptions(
        python_path=python_path if python_path.is_absolute() else PROJECT_ROOT / python_path,
        worker_path=worker_path if worker_path.is_absolute() else PROJECT_ROOT / worker_path,
        cache_dir=cache_dir if cache_dir.is_absolute() else PROJECT_ROOT / cache_dir,
        timeout_s=float(os.getenv("PARKING_OCR_TIMEOUT_S", "30")),
        max_samples=int(os.getenv("PARKING_OCR_MAX_SAMPLES", "5")),
        detector_model_path=(
            detector_path if detector_path.is_absolute() else PROJECT_ROOT / detector_path
        ),
        detector_confidence=float(os.getenv("PARKING_PLATE_CONFIDENCE", "0.15")),
        detector_image_size=int(os.getenv("PARKING_PLATE_IMAGE_SIZE", "960")),
        detector_device=os.getenv("PARKING_PLATE_DEVICE", "cpu"),
        max_regions=int(os.getenv("PARKING_PLATE_MAX_REGIONS", "2")),
        min_ocr_confidence=float(os.getenv("PARKING_OCR_MIN_CONFIDENCE", "0.6")),
        ocr_model_path=_project_path(
            "PARKING_PLATE_OCR_MODEL", "models/plate_ocr/cct_s_v2_global.onnx"
        ),
        ocr_config_path=_project_path(
            "PARKING_PLATE_OCR_CONFIG", "models/plate_ocr/cct_s_v2_global_plate_config.yaml"
        ),
    )


def _project_path(variable: str, default: str) -> Path:
    path = Path(os.getenv(variable, default)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass
class AppSettings:
    """Core runtime settings."""

    app_name: str = "Hệ thống Quản lý Bãi giữ xe"
    app_version: str = "6.0.0 (Giai đoạn 6)"
    data_dir: Path = PROJECT_ROOT / "data"
    db_path: Path = PROJECT_ROOT / "data" / "parking.db"
    evidence_dir: Path = PROJECT_ROOT / "data" / "evidence"
    vision_options: VisionOptions = field(default_factory=_vision_options)
    plate_recognition_options: PlateRecognitionOptions = field(
        default_factory=_plate_recognition_options
    )
    video_options: VideoOptions = field(
        default_factory=lambda: VideoOptions(
            open_timeout_s=float(os.getenv("PARKING_VIDEO_OPEN_TIMEOUT_S", "8")),
            read_timeout_s=float(os.getenv("PARKING_VIDEO_READ_TIMEOUT_S", "4")),
            reconnect_delay_s=float(os.getenv("PARKING_VIDEO_RECONNECT_DELAY_S", "2")),
            stale_after_s=float(os.getenv("PARKING_VIDEO_STALE_AFTER_S", "3")),
        )
    )

    def ensure_directories(self) -> None:
        """Create necessary data folders."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)


def seed_initial_accounts(session_manager: DatabaseSessionManager) -> None:
    """Seed initial administrator and operator accounts if database is empty."""
    with session_manager.session() as session:
        user_repo = SqlAlchemyUserRepository(session)
        if user_repo.count() > 0:
            return

        initial_users = [
            User(
                id=None,
                username="admin",
                password_hash=hash_password("admin123"),
                full_name="Quản trị viên Hệ thống",
                role=UserRole.ADMIN,
                status=UserStatus.ACTIVE,
            ),
            User(
                id=None,
                username="quanly",
                password_hash=hash_password("quanly123"),
                full_name="Nguyễn Văn Quản Lý",
                role=UserRole.MANAGER,
                status=UserStatus.ACTIVE,
            ),
            User(
                id=None,
                username="nhanvien",
                password_hash=hash_password("nhanvien123"),
                full_name="Trần Thị Nhân Viên",
                role=UserRole.STAFF,
                status=UserStatus.ACTIVE,
            ),
        ]
        for user in initial_users:
            user_repo.save(user)
