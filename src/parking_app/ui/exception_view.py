"""Manager exception review and resolution (QL-04, M08, M10)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.audit_service import AuditService
from parking_app.application.parking_service import ParkingService
from parking_app.domain.models import ExceptionCase


class ExceptionManagementWidget(QWidget):
    """Display anomalies, associated evidence, operator and processing state."""

    case_updated = Signal()

    def __init__(
        self,
        audit_service: AuditService,
        parking_service: ParkingService,
        actor,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.audit_service = audit_service
        self.parking_service = parking_service
        self.actor = actor
        self._cases: list[ExceptionCase] = []
        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("Chưa xử lý", False)
        self.status_filter.addItem("Đã xử lý", True)
        self.status_filter.addItem("Tất cả", None)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        controls.addWidget(QLabel("Trạng thái:"))
        controls.addWidget(self.status_filter)
        self.refresh_button = QPushButton("Làm mới")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.resolve_button = QPushButton("Đánh dấu đã xử lý")
        self.resolve_button.clicked.connect(self._resolve_selected)
        controls.addWidget(self.resolve_button)
        controls.addStretch()
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Thời gian", "Loại bất thường", "Biển số", "Nội dung", "Nhân viên", "Trạng thái"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        splitter.addWidget(self.table)

        evidence_panel = QWidget()
        evidence_layout = QVBoxLayout(evidence_panel)
        self.details = QLabel("Chọn một trường hợp để xem thông tin và ảnh bằng chứng.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.evidence_preview = QLabel("Chưa có ảnh bằng chứng")
        self.evidence_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.evidence_preview.setMinimumSize(250, 180)
        self.evidence_preview.setStyleSheet("border: 1px solid #9e9e9e; background: #f5f5f5;")
        evidence_layout.addWidget(self.details)
        evidence_layout.addWidget(self.evidence_preview, 1)
        splitter.addWidget(evidence_panel)
        splitter.setSizes([750, 350])
        layout.addWidget(splitter, 1)

    def refresh(self) -> None:
        try:
            cases = self.audit_service.list_exceptions(
                self.actor,
                handled=self.status_filter.currentData(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi tải ngoại lệ", f"Không thể tải danh sách:\n{exc}")
            return
        self._cases = cases
        self.table.setRowCount(len(cases))
        for row, case in enumerate(cases):
            values = (
                case.timestamp.astimezone().strftime("%H:%M:%S %d/%m/%Y"),
                case.category,
                case.plate or "—",
                case.description,
                case.operator,
                "Đã xử lý" if case.handled else "Chưa xử lý",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, case.reference)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self._show_selected()

    def _show_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._cases):
            self.details.setText("Chọn một trường hợp để xem thông tin và ảnh bằng chứng.")
            self.evidence_preview.setPixmap(QPixmap())
            self.evidence_preview.setText("Chưa có ảnh bằng chứng")
            self.resolve_button.setEnabled(False)
            return
        case = self._cases[row]
        self.details.setText(
            f"{case.category}\n"
            f"Mã lượt/sự cố: {case.session_code or case.reference}\n"
            f"Kết quả/lý do: {case.description}\n"
            f"Nhân viên: {case.operator}\n"
            f"Trạng thái: {'Đã xử lý' if case.handled else 'Chưa xử lý'}"
        )
        self.resolve_button.setEnabled(not case.handled)
        if case.evidence_path and Path(case.evidence_path).is_file():
            pixmap = QPixmap(case.evidence_path)
            self.evidence_preview.setPixmap(
                pixmap.scaled(
                    self.evidence_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.evidence_preview.setText("")
        else:
            self.evidence_preview.setPixmap(QPixmap())
            self.evidence_preview.setText("Không có ảnh bằng chứng khả dụng")

    def _resolve_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._cases):
            QMessageBox.warning(self, "Chưa chọn ngoại lệ", "Hãy chọn một trường hợp.")
            return
        case = self._cases[row]
        if case.handled:
            return
        from PySide6.QtWidgets import QInputDialog

        reason, accepted = QInputDialog.getText(
            self,
            "Xử lý ngoại lệ",
            "Ghi chú kết quả xử lý:",
        )
        if not accepted:
            return
        try:
            if case.session_code:
                self.parking_service.resolve_session_attention(
                    self.actor,
                    case.session_code,
                    reason,
                )
            else:
                self.audit_service.resolve_exception(self.actor, case.reference, reason)
        except Exception as exc:
            QMessageBox.critical(self, "Không thể xử lý ngoại lệ", str(exc))
            return
        self.refresh()
        self.case_updated.emit()
