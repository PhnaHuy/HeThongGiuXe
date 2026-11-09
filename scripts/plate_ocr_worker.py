"""Offline Fast Plate OCR protocol; run in the isolated .venv-alpr environment."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

from ocr_worker import _read_request


def main() -> int:
    try:
        import cv2
        import numpy as np
        from fast_plate_ocr import LicensePlateRecognizer

        model = Path(os.environ["PARKING_PLATE_OCR_MODEL"])
        config = Path(os.environ["PARKING_PLATE_OCR_CONFIG"])
        if not model.is_file() or not config.is_file():
            raise FileNotFoundError("Thiếu model hoặc cấu hình Fast Plate OCR cục bộ.")
        decoded = []
        for data in _read_request():
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Không giải mã được ảnh biển số.")
            decoded.append(image)
        with contextlib.redirect_stdout(sys.stderr):
            recognizer = LicensePlateRecognizer(
                onnx_model_path=model, plate_config_path=config, device="cpu"
            )
            conversion = (
                cv2.COLOR_BGR2RGB
                if recognizer.config.image_color_mode == "rgb"
                else cv2.COLOR_BGR2GRAY
            )
            decoded = [cv2.cvtColor(image, conversion) for image in decoded]
            predictions = recognizer.run(decoded, return_confidence=True)
        results = []
        for prediction in predictions:
            probabilities = prediction.char_probs
            confidence = (
                float(np.mean(probabilities[: len(prediction.plate)]))
                if probabilities is not None and prediction.plate
                else 0.0
            )
            results.append({"text": prediction.plate, "confidence": confidence})
        print("PARKING_OCR_RESULT:" + json.dumps({"results": results}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print("PARKING_OCR_ERROR:" + json.dumps({"error": str(exc)[:500]}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
