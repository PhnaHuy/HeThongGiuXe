"""Administrator capacity configuration (QT-04, M07)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.parking_service import ParkingService


class CapacityManagementWidget(QWidget):
    """Persist per-type capacities and refresh the live summary."""

    capacity_updated = Signal()

    def __init__(self, parking_service: ParkingService, actor, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.parking_service = parking_service
        self.actor = actor
        layout = QVBoxLayout(self)
        group = QGroupBox("Cấu hình sức chứa theo loại phương tiện")
        form = QFormLayout(group)
        self.motorcycle_capacity = QSpinBox()
        self.car_capacity = QSpinBox()
        for control in (self.motorcycle_capacity, self.car_capacity):
            control.setRange(0, 2_147_483_647)
        form.addRow("Sức chứa xe máy:", self.motorcycle_capacity)
        form.addRow("Sức chứa ô tô:", self.car_capacity)
        layout.addWidget(group)
        self.total_hint = QLabel(
            "Sức chứa toàn bãi được tính bằng tổng sức chứa theo loại. "
            "Cấu hình khu vực riêng sẽ bổ sung khi có mô hình phân khu."
        )
        self.total_hint.setWordWrap(True)
        layout.addWidget(self.total_hint)
        self.save_button = QPushButton("Lưu sức chứa")
        self.save_button.clicked.connect(self._save)
        layout.addWidget(self.save_button)
        layout.addStretch()
        self._load()

    def _load(self) -> None:
        self.motorcycle_capacity.setValue(self.parking_service.motorcycle_capacity)
        self.car_capacity.setValue(self.parking_service.car_capacity)

    def _save(self) -> None:
        try:
            self.parking_service.update_capacity(
                self.actor,
                self.motorcycle_capacity.value(),
                self.car_capacity.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Không thể lưu sức chứa", str(exc))
            return
        self.capacity_updated.emit()
        QMessageBox.information(self, "Đã lưu", "Cấu hình sức chứa đã được lưu.")
