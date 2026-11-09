"""Evidence image file storage manager."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from parking_app.domain.enums import EvidenceType, VehicleType
from parking_app.domain.exceptions import ImageStorageError


class EvidenceStorage:
    """Safely saves and retrieves photographic evidence files."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_image(
        self,
        image_data: bytes | Any,
        session_code: str,
        evidence_type: EvidenceType,
    ) -> str:
        """Save evidence image data under a date-partitioned safe directory.

        Returns the absolute string path to the created image.
        Raises ImageStorageError if disk write fails.
        """
        now = datetime.now(UTC)
        sub_dir = self.base_dir / now.strftime("%Y%m%d")
        sub_dir.mkdir(parents=True, exist_ok=True)

        # Invariant: Never use raw customer names or unescaped strings in file paths
        safe_session = "".join(c for c in session_code if c.isalnum() or c in ("-", "_"))
        unique_token = uuid.uuid4().hex[:8]
        file_name = f"ev_{safe_session}_{evidence_type.value.lower()}_{unique_token}.jpg"
        target_path = sub_dir / file_name

        try:
            if isinstance(image_data, bytes):
                target_path.write_bytes(image_data)
            else:
                # Assume numpy array image
                import cv2

                success = cv2.imwrite(str(target_path), image_data)
                if not success:
                    raise ImageStorageError(f"OpenCV không ghi được tệp ảnh tại {target_path}.")
        except Exception as e:
            if target_path.exists():
                target_path.unlink(missing_ok=True)
            raise ImageStorageError(f"Không thể lưu ảnh bằng chứng: {e}") from e

        return str(target_path)

    def remove_file(self, file_path: str | None) -> None:
        """Remove an image file if a database transaction aborts."""
        if not file_path:
            return
        path = Path(file_path)
        if path.is_file():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def create_synthetic_image(
        self,
        plate_text: str,
        vehicle_type: VehicleType,
        is_entry: bool = True,
    ) -> bytes:
        """Generate a synthetic vehicle evidence image fixture for testing."""
        import cv2
        import numpy as np

        # Create 640x360 image
        bg_color = (220, 225, 230) if is_entry else (210, 215, 220)
        img = np.full((360, 640, 3), bg_color, dtype=np.uint8)

        # Vehicle silhouette box
        v_color = (80, 110, 160) if vehicle_type == VehicleType.CAR else (140, 90, 60)
        cv2.rectangle(img, (140, 100), (500, 280), v_color, -1)

        # License plate box
        cv2.rectangle(img, (230, 210), (410, 260), (255, 255, 255), -1)
        cv2.rectangle(img, (230, 210), (410, 260), (0, 0, 0), 2)

        # Text: Direction and Plate
        direction = "CỔNG VÀO (ENTRY)" if is_entry else "CỔNG RA (EXIT)"
        cv2.putText(img, direction, (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 50, 200), 2)
        cv2.putText(
            img,
            f"Loai: {vehicle_type.display_name}",
            (30, 85),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (50, 50, 50),
            1,
        )
        cv2.putText(img, plate_text, (245, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        # Encode to JPEG bytes
        success, encoded = cv2.imencode(".jpg", img)
        if not success:
            raise RuntimeError("Encode synthetic jpeg failed.")
        return encoded.tobytes()
