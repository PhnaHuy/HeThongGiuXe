"""Asynchronous plate recognition so OCR never blocks the desktop UI."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from parking_app.application.plate_recognition import PlateRecognitionUseCase
from parking_app.domain.plate import PlateRecognition


class PlateRecognitionWorker(QThread):
    completed = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        candidate_id: str,
        source_images: tuple[bytes, ...],
        service: PlateRecognitionUseCase,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.candidate_id = candidate_id
        self.source_images = source_images
        self.service = service

    def run(self) -> None:
        try:
            result: PlateRecognition = self.service.recognize(self.source_images)
        except Exception as exc:
            self.failed.emit(self.candidate_id, str(exc))
            return
        self.completed.emit(self.candidate_id, result)


class PlateRecognitionWarmupWorker(QThread):
    completed = Signal()
    failed = Signal(str)

    def __init__(self, service: PlateRecognitionUseCase, parent=None) -> None:
        super().__init__(parent)
        self.service = service

    def run(self) -> None:
        warmup = getattr(self.service, "warmup", None)
        if not callable(warmup):
            self.completed.emit()
            return
        try:
            warmup()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit()
