"""Isolated subprocess adapter for the dedicated PaddleOCR environment."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from typing import Protocol


class PlateOCRFailure(RuntimeError):
    """An explicit OCR worker, model, or communication failure."""


class OCRRuntimeOptions(Protocol):
    python_path: Path
    worker_path: Path
    cache_dir: Path
    timeout_s: float


class PaddleOCRSubprocess:
    def __init__(self, options: OCRRuntimeOptions) -> None:
        self.options = options

    def recognize(self, crops: tuple[bytes, ...]) -> tuple[tuple[str, float], ...]:
        if not crops:
            return ()
        payload = json.dumps(
            {"images": [base64.b64encode(crop).decode("ascii") for crop in crops]},
            separators=(",", ":"),
        )
        environment = os.environ.copy()
        environment.update(
            {
                "PADDLE_PDX_CACHE_HOME": str(self.options.cache_dir),
                "PADDLE_PDX_MODEL_SOURCE": "BOS",
                "FLAGS_use_mkldnn": "0",
            }
        )
        for attribute, variable in (
            ("ocr_model_path", "PARKING_PLATE_OCR_MODEL"),
            ("ocr_config_path", "PARKING_PLATE_OCR_CONFIG"),
        ):
            path = getattr(self.options, attribute, None)
            if path is not None:
                environment[variable] = str(path.resolve())
        try:
            completed = subprocess.run(
                [str(self.options.python_path), str(self.options.worker_path)],
                input=payload,
                capture_output=True,
                check=False,
                cwd=self.options.worker_path.parent.parent,
                env=environment,
                text=True,
                timeout=self.options.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise PlateOCRFailure(
                f"OCR vượt quá thời gian chờ {self.options.timeout_s:g} giây."
            ) from exc
        except OSError as exc:
            raise PlateOCRFailure(f"Không khởi chạy được môi trường OCR: {exc}") from exc

        result_line = self._find_response(completed.stdout, "PARKING_OCR_RESULT:")
        error_line = self._find_response(completed.stdout, "PARKING_OCR_ERROR:")
        if error_line is not None:
            try:
                message = json.loads(error_line)["error"]
            except (KeyError, TypeError, json.JSONDecodeError):
                message = "Tiến trình PaddleOCR báo lỗi không đúng định dạng."
            raise PlateOCRFailure(str(message))
        if completed.returncode != 0:
            detail = completed.stderr.strip()[-1000:]
            raise PlateOCRFailure(detail or "Tiến trình PaddleOCR kết thúc với lỗi.")
        if result_line is None:
            raise PlateOCRFailure("Tiến trình PaddleOCR không trả kết quả hợp lệ.")
        try:
            results = json.loads(result_line)["results"]
            return tuple((str(item["text"]), float(item["confidence"])) for item in results)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PlateOCRFailure("Kết quả trả về từ PaddleOCR không đúng định dạng.") from exc

    @staticmethod
    def _find_response(output: str, prefix: str) -> str | None:
        return next(
            (
                line.removeprefix(prefix)
                for line in reversed(output.splitlines())
                if line.startswith(prefix)
            ),
            None,
        )
