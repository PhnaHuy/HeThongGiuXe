"""Run database/report work outside the Qt GUI thread."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class OperationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:
        try:
            result = self.operation()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)
