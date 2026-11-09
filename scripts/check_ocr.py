"""Run a local synthetic or user-selected image through the G5 OCR pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _synthetic_vehicle() -> np.ndarray:
    image = np.full((220, 360, 3), (110, 150, 195), dtype=np.uint8)
    cv2.rectangle(image, (80, 120), (280, 180), (255, 255, 255), -1)
    cv2.rectangle(image, (80, 120), (280, 180), (0, 0, 0), 3)
    cv2.putText(
        image,
        "51A12345",
        (92, 162),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        type=Path,
        help="Optional vehicle/plate image; otherwise use a synthetic plate fixture.",
    )
    arguments = parser.parse_args()
    if arguments.image:
        image = cv2.imread(str(arguments.image))
        if image is None:
            parser.error(f"Không đọc được ảnh: {arguments.image}")
    else:
        image = _synthetic_vehicle()

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from parking_app.application.plate_recognition import PlateRecognitionService
    from parking_app.config.settings import AppSettings

    success, encoded = cv2.imencode(".jpg", image)
    if not success:
        raise RuntimeError("Không mã hóa được ảnh thử OCR.")
    recognition = PlateRecognitionService(AppSettings().plate_recognition_options).recognize(
        (encoded.tobytes(),)
    )
    print(
        json.dumps(
            {
                "raw_text": recognition.raw_text,
                "proposed_plate": recognition.proposed_plate,
                "confidence": recognition.confidence,
                "samples_considered": recognition.samples_considered,
                "plate_region_detected": recognition.plate_image_data is not None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if recognition.proposed_plate else 2


if __name__ == "__main__":
    raise SystemExit(main())
