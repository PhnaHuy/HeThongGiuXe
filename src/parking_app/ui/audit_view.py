"""Audit Log Viewer UI Widget (M10, QT-01, NV-01)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.audit_service import AuditService
from parking_app.domain.enums import AuditAction
from parking_app.domain.models import User


class AuditLogWidget(QWidget):
    """View presenting system audit trails."""

    def __init__(self, audit_service: AuditService, current_user: User, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.audit_service = audit_service
        self.current_user = current_user

        self._init_ui()
        self.refresh_logs()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("<b>Nhật ký kiểm toán hệ thống (Audit Trail):</b>"))
        top_layout.addStretch()

        self.refresh_btn = QPushButton("Làm mới")
        self.refresh_btn.clicked.connect(self.refresh_logs)
        top_layout.addWidget(self.refresh_btn)

        layout.addLayout(top_layout)

        filters = QHBoxLayout()
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("ID tài khoản")
        self.from_date_input = QLineEdit()
        self.from_date_input.setPlaceholderText("Từ ngày (YYYY-MM-DD)")
        self.to_date_input = QLineEdit()
        self.to_date_input.setPlaceholderText("Đến ngày (YYYY-MM-DD)")
        self.action_filter = QComboBox()
        self.action_filter.addItem("Tất cả hành động", None)
        for action in AuditAction:
            self.action_filter.addItem(action.value, action)
        self.apply_filter_btn = QPushButton("Lọc nhật ký")
        self.apply_filter_btn.clicked.connect(self.refresh_logs)
        filters.addWidget(self.user_id_input)
        filters.addWidget(self.action_filter)
        filters.addWidget(self.from_date_input)
        filters.addWidget(self.to_date_input)
        filters.addWidget(self.apply_filter_btn)
        layout.addLayout(filters)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Thời gian", "Tài khoản", "Hành động", "Đối tượng", "Chi tiết", "Lý do"]
        )
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

    def refresh_logs(self) -> None:
        try:
            user_text = self.user_id_input.text().strip()
            if user_text and not user_text.isdigit():
                raise ValueError("ID tài khoản phải là số nguyên dương.")
            from_time, before_time = self._date_bounds()
            logs = self.audit_service.list_recent_audits(
                self.current_user,
                limit=1000,
                user_id=int(user_text) if user_text else None,
                action=self.action_filter.currentData(),
                from_time=from_time,
                before_time=before_time,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Bộ lọc không hợp lệ", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi tải nhật ký", f"Không thể tải nhật ký:\n{exc}")
            return

        self.table.setRowCount(len(logs))
        for row, entry in enumerate(logs):
            time_str = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            self.table.setItem(row, 0, QTableWidgetItem(time_str))
            self.table.setItem(row, 1, QTableWidgetItem(entry.username or "Hệ thống"))
            self.table.setItem(row, 2, QTableWidgetItem(entry.action.value))
            self.table.setItem(
                row, 3, QTableWidgetItem(f"{entry.target_type}:{entry.target_id or ''}")
            )

            detail_parts = []
            if entry.old_values:
                detail_parts.append(f"Cũ: {json.dumps(entry.old_values, ensure_ascii=False)}")
            if entry.new_values:
                detail_parts.append(f"Mới: {json.dumps(entry.new_values, ensure_ascii=False)}")
            self.table.setItem(row, 4, QTableWidgetItem(" | ".join(detail_parts)))
            self.table.setItem(row, 5, QTableWidgetItem(entry.reason or ""))

    def _date_bounds(self) -> tuple[datetime | None, datetime | None]:
        from_text = self.from_date_input.text().strip()
        to_text = self.to_date_input.text().strip()
        try:
            start_date = date.fromisoformat(from_text) if from_text else None
            end_date = date.fromisoformat(to_text) if to_text else None
        except ValueError as exc:
            raise ValueError("Ngày phải đúng định dạng YYYY-MM-DD.") from exc
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("Ngày bắt đầu không được sau ngày kết thúc.")
        start = (
            datetime.combine(start_date, time.min).astimezone(UTC)
            if start_date is not None
            else None
        )
        before = (
            datetime.combine(end_date + timedelta(days=1), time.min).astimezone(UTC)
            if end_date is not None
            else None
        )
        return start, before
