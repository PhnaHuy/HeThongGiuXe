"""One-shot OCR protocol entry point; run with the isolated .venv-ocr-313 Python."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any


def _read_request() -> list[bytes]:
    request = json.load(sys.stdin)
    encoded_images = request.get("images")
    if not isinstance(encoded_images, list) or not 1 <= len(encoded_images) <= 20:
        raise ValueError("Số vùng biển gửi tới OCR phải nằm trong khoảng 1–20.")
    images = [base64.b64decode(value, validate=True) for value in encoded_images]
    if any(not image or len(image) > 5_000_000 for image in images):
        raise ValueError("Ảnh OCR rỗng hoặc vượt quá giới hạn kích thước.")
    return images


def _reading_order(item: dict) -> tuple[str, float]:
    """Read top row first, then left to right, independent of detector order."""
    import numpy as np

    texts = item.get("rec_texts", ())
    scores = item.get("rec_scores", ())
    polygons = item.get("rec_polys", ())
    if len(texts) != len(scores):
        raise ValueError("OCR texts and scores have different lengths")
    order = list(range(len(texts)))
    if len(polygons) == len(texts) and len(texts):
        bounds = [np.asarray(poly).reshape(-1, 2) for poly in polygons]
        centers = [float(poly[:, 1].mean()) for poly in bounds]
        heights = [float(np.ptp(poly[:, 1])) for poly in bounds]
        tolerance = max(1.0, float(np.median(heights)) * 0.5)
        rows: list[list[int]] = []
        for index in sorted(order, key=lambda i: centers[i]):
            if not rows or abs(centers[index] - centers[rows[-1][0]]) > tolerance:
                rows.append([])
            rows[-1].append(index)
        order = [
            index
            for row in rows
            for index in sorted(row, key=lambda i: float(bounds[i][:, 0].min()))
        ]
    text = "\n".join(str(texts[index]).strip() for index in order)
    confidence = sum(float(score) for score in scores) / len(scores) if len(scores) else 0.0
    return text, confidence


def _run(images: list[bytes]) -> list[dict[str, Any]]:
    cache = Path(os.environ["PADDLE_PDX_CACHE_HOME"])
    model_names = ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec")
    for model_name in model_names:
        model_dir = cache / "official_models" / model_name
        if (
            not (model_dir / "inference.yml").is_file()
            and not (model_dir / "config.json").is_file()
        ):
            raise FileNotFoundError(f"Thiếu model OCR cục bộ: {model_name}")

    import cv2
    import numpy as np

    decoded = []
    for encoded_image in images:
        image = cv2.imdecode(np.frombuffer(encoded_image, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Không giải mã được ảnh gửi tới OCR.")
        decoded.append(image)

    from paddleocr import PaddleOCR

    with contextlib.redirect_stdout(sys.stderr), contextlib.redirect_stderr(sys.stderr):
        ocr = PaddleOCR(
            text_detection_model_name=model_names[0],
            text_recognition_model_name=model_names[1],
            text_detection_model_dir=str(cache / "official_models" / model_names[0]),
            text_recognition_model_dir=str(cache / "official_models" / model_names[1]),
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
        predictions = [ocr.predict(image) for image in decoded]

    output = []
    for prediction in predictions:
        item = prediction[0] if prediction else {}
        text, confidence = _reading_order(item)
        output.append({"text": text, "confidence": confidence})
    return output


def main() -> int:
    try:
        images = _read_request()
        results = _run(images)
    except Exception as exc:
        print("PARKING_OCR_ERROR:" + json.dumps({"error": str(exc)[:500]}, ensure_ascii=True))
        return 1
    print("PARKING_OCR_RESULT:" + json.dumps({"results": results}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
