"""Persistent subprocess adapter for the dedicated PaddleOCR environment."""

from __future__ import annotations

import base64
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Protocol, TextIO

from parking_app.domain.plate import PlateOCRResult


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
        self._process: subprocess.Popen | None = None
        self._responses: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._ready = False

    def warmup(self) -> None:
        with self._lock:
            self._ensure_ready()

    def recognize(self, images: tuple[bytes, ...]) -> tuple[PlateOCRResult, ...]:
        if not images:
            return ()
        payload = json.dumps(
            {"images": [base64.b64encode(image).decode("ascii") for image in images]},
            separators=(",", ":"),
        )
        with self._lock:
            self._ensure_ready()
            process = self._process
            if process is None or process.stdin is None:
                raise PlateOCRFailure("Tiến trình PaddleOCR chưa sẵn sàng.")
            try:
                process.stdin.write(payload + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._stop_process()
                raise PlateOCRFailure("Mất kết nối với tiến trình PaddleOCR.") from exc

            marker, content = self._read_message()
            if marker == "PARKING_OCR_ERROR:":
                try:
                    message = json.loads(content)["error"]
                except (KeyError, TypeError, json.JSONDecodeError):
                    message = "Tiến trình PaddleOCR báo lỗi không đúng định dạng."
                raise PlateOCRFailure(str(message))
            if marker != "PARKING_OCR_RESULT:":
                self._stop_process()
                raise PlateOCRFailure("Tiến trình PaddleOCR không trả kết quả hợp lệ.")
            try:
                results = json.loads(content)["results"]
                return tuple(
                    PlateOCRResult(
                        text=str(item["text"]),
                        confidence=float(item["confidence"]),
                        plate_image_data=(
                            base64.b64decode(item["plate_image"], validate=True)
                            if item.get("plate_image")
                            else None
                        ),
                    )
                    for item in results
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise PlateOCRFailure("Kết quả trả về từ PaddleOCR không đúng định dạng.") from exc

    def _ensure_ready(self) -> None:
        if self._ready and self._process is not None and self._process.poll() is None:
            return
        self._stop_process()
        environment = os.environ.copy()
        environment.update(
            {
                "PADDLE_PDX_CACHE_HOME": str(self.options.cache_dir),
                "PADDLE_PDX_MODEL_SOURCE": "BOS",
                "FLAGS_use_mkldnn": "0",
            }
        )
        try:
            process = subprocess.Popen(
                [str(self.options.python_path), str(self.options.worker_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.options.worker_path.parent.parent,
                env=environment,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as exc:
            raise PlateOCRFailure(f"Không khởi chạy được môi trường OCR: {exc}") from exc
        if process.stdout is None:
            process.terminate()
            raise PlateOCRFailure("Tiến trình PaddleOCR không mở được kênh kết quả.")
        self._process = process
        self._responses = queue.Queue()
        threading.Thread(
            target=self._read_stdout,
            args=(process.stdout, self._responses),
            daemon=True,
        ).start()
        marker, content = self._read_message()
        if marker == "PARKING_OCR_ERROR:":
            self._stop_process()
            try:
                message = json.loads(content)["error"]
            except (KeyError, TypeError, json.JSONDecodeError):
                message = "Không khởi tạo được PaddleOCR."
            raise PlateOCRFailure(str(message))
        if marker != "PARKING_OCR_READY:":
            self._stop_process()
            raise PlateOCRFailure("Tiến trình PaddleOCR không hoàn tất khởi tạo.")
        self._ready = True

    @staticmethod
    def _read_stdout(stream: TextIO, responses: queue.Queue[str | None]) -> None:
        try:
            for line in stream:
                responses.put(line.rstrip("\r\n"))
        finally:
            responses.put(None)

    def _read_message(self) -> tuple[str | None, str]:
        deadline = time.monotonic() + self.options.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._stop_process()
                raise PlateOCRFailure(
                    f"OCR vượt quá thời gian chờ {self.options.timeout_s:g} giây."
                )
            try:
                line = self._responses.get(timeout=remaining)
            except queue.Empty as exc:
                self._stop_process()
                raise PlateOCRFailure(
                    f"OCR vượt quá thời gian chờ {self.options.timeout_s:g} giây."
                ) from exc
            if line is None:
                process = self._process
                exit_code = process.poll() if process is not None else None
                self._stop_process()
                if exit_code not in (None, 0):
                    raise PlateOCRFailure(f"Tiến trình PaddleOCR kết thúc với mã {exit_code}.")
                return None, ""
            for prefix in ("PARKING_OCR_READY:", "PARKING_OCR_RESULT:", "PARKING_OCR_ERROR:"):
                if line.startswith(prefix):
                    return prefix, line.removeprefix(prefix)

    def close(self) -> None:
        with self._lock:
            self._stop_process()

    def _stop_process(self) -> None:
        process, self._process = self._process, None
        self._ready = False
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
