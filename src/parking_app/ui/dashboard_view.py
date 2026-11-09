"""Manager dashboard and period statistics (QL-01, QL-03, M07, M09)."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.parking_service import ParkingService
from parking_app.ui.operation_worker import OperationWorker


class ParkingDashboardWidget(QWidget):
    """Show current occupancy and configurable-period entry/exit statistics."""

    operations_idle = Signal()

    def __init__(self, parking_service: ParkingService, actor, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.parking_service = parking_service
        self.actor = actor
        self._report = []
        self._refresh_worker: OperationWorker | None = None
        self._refresh_pending = False
        self._export_worker: OperationWorker | None = None
        self._init_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        occupancy = QGroupBox("Tình trạng bãi hiện tại")
        occupancy_layout = QFormLayout(occupancy)
        self.total_occupancy = QLabel("—")
        self.motorcycle_occupancy = QLabel("—")
        self.car_occupancy = QLabel("—")
        self.updated_at = QLabel("Chưa cập nhật")
        occupancy_layout.addRow("Tổng số xe đang gửi / sức chứa:", self.total_occupancy)
        occupancy_layout.addRow("Xe máy đang gửi / còn chỗ:", self.motorcycle_occupancy)
        occupancy_layout.addRow("Ô tô đang gửi / còn chỗ:", self.car_occupancy)
        occupancy_layout.addRow("Cập nhật lúc:", self.updated_at)
        layout.addWidget(occupancy)

        period = QGroupBox("Thống kê lượt vào / ra")
        period_layout = QVBoxLayout(period)
        filters = QHBoxLayout()
        self.from_date = QLineEdit()
        self.from_date.setPlaceholderText("Từ ngày (YYYY-MM-DD)")
        self.to_date = QLineEdit()
        self.to_date.setPlaceholderText("Đến ngày (YYYY-MM-DD)")
        self.apply_button = QPushButton("Thống kê")
        self.apply_button.clicked.connect(self.refresh)
        filters.addWidget(self.from_date)
        filters.addWidget(self.to_date)
        filters.addWidget(self.apply_button)
        period_layout.addLayout(filters)
        self.statistics = QLabel("Nhập khoảng ngày hoặc để trống để xem toàn bộ lịch sử.")
        self.statistics.setWordWrap(True)
        period_layout.addWidget(self.statistics)
        period_layout.addWidget(
            QLabel(
                "Danh sách gồm lượt có thời gian vào hoặc ra trong khoảng đã chọn; "
                "phân loại theo thông tin lúc xe vào."
            )
        )
        self.report_tabs = QTabWidget()
        self.registered_table = self._make_table()
        self.guest_table = self._make_table()
        self.report_tabs.addTab(self.registered_table, "Xe đã đăng ký (0)")
        self.report_tabs.addTab(self.guest_table, "Khách vãng lai (0)")
        period_layout.addWidget(self.report_tabs)
        self.export_button = QPushButton("Xuất CSV…")
        self.export_button.clicked.connect(self._export_csv)
        period_layout.addWidget(self.export_button)
        layout.addWidget(period)

    def refresh(self) -> None:
        try:
            start, before = self._date_bounds()
        except ValueError as exc:
            QMessageBox.warning(self, "Khoảng ngày không hợp lệ", str(exc))
            return

        if self._refresh_worker is not None:
            self._refresh_pending = True
            return

        worker = OperationWorker(
            lambda: (
                self.parking_service.get_capacity_summary(),
                self.parking_service.get_statistics(self.actor, start, before),
                self.parking_service.get_activity_report(self.actor, start, before),
            )
        )
        self._refresh_worker = worker
        worker.succeeded.connect(self._refresh_succeeded)
        worker.failed.connect(self._refresh_failed)
        worker.finished.connect(self._refresh_finished)
        worker.start()

    def _refresh_succeeded(self, result: object) -> None:
        summary, stats, report = result
        self._report = report
        self._update_report_tables()
        self.total_occupancy.setText(
            f"{summary.total_active} / {summary.total_capacity} (còn {summary.total_remaining})"
        )
        self.motorcycle_occupancy.setText(
            f"{summary.motorcycle_active} / {summary.motorcycle_capacity} "
            f"(còn {summary.motorcycle_remaining})"
        )
        self.car_occupancy.setText(
            f"{summary.car_active} / {summary.car_capacity} (còn {summary.car_remaining})"
        )
        self.updated_at.setText(datetime.now().astimezone().strftime("%H:%M:%S %d/%m/%Y"))
        full_note = " — CẢNH BÁO: đã đầy" if summary.is_full else ""
        self.total_occupancy.setStyleSheet(
            "color: #b71c1c; font-weight: bold;" if summary.is_full else "font-weight: bold;"
        )
        self.total_occupancy.setToolTip(full_note.strip())
        self.statistics.setText(
            f"Xe máy: {stats.motorcycle_entries} lượt vào, {stats.motorcycle_exits} lượt ra\n"
            f"Ô tô: {stats.car_entries} lượt vào, {stats.car_exits} lượt ra\n"
            f"Tổng: {stats.total_entries} lượt vào, {stats.total_exits} lượt ra"
        )

    def _refresh_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Lỗi tải tổng quan", f"Không thể tải dữ liệu:\n{message}")

    def _refresh_finished(self) -> None:
        worker = self.sender()
        if worker is not self._refresh_worker:
            return
        self._refresh_worker = None
        worker.deleteLater()
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh)
        else:
            self._emit_operations_idle()

    @staticmethod
    def _make_table() -> QTableWidget:
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            ["Mã lượt", "Biển số", "Loại xe", "Thời gian vào", "Thời gian ra", "Trạng thái"]
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    @staticmethod
    def _row(session) -> list[str]:
        def format_time(value):
            if value is None:
                return ""
            # SQLite returns stored UTC values without timezone metadata.
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")

        return [
            session.session_code,
            session.snapshot_display_plate,
            session.snapshot_vehicle_type.display_name,
            format_time(session.entry_time),
            format_time(session.exit_time),
            session.status.display_name,
        ]

    def _update_report_tables(self) -> None:
        for index, (table, registered, title) in enumerate(
            (
                (self.registered_table, True, "Xe đã đăng ký"),
                (self.guest_table, False, "Khách vãng lai"),
            )
        ):
            rows = [item for item in self._report if item.is_registered_customer == registered]
            table.setRowCount(len(rows))
            for row_index, item in enumerate(rows):
                for column, value in enumerate(self._row(item)):
                    table.setItem(row_index, column, QTableWidgetItem(value))
            self.report_tabs.setTabText(index, f"{title} ({len(rows)})")

    def _export_csv(self) -> None:
        try:
            start, before = self._date_bounds()
        except ValueError as exc:
            QMessageBox.warning(self, "Không thể xuất thống kê", str(exc))
            return
        if self._export_worker is not None:
            return

        worker = OperationWorker(
            lambda: self.parking_service.get_activity_report(self.actor, start, before)
        )
        self._export_worker = worker
        self.export_button.setEnabled(False)
        worker.succeeded.connect(self._export_succeeded)
        worker.failed.connect(self._export_failed)
        worker.finished.connect(self._export_finished)
        worker.start()

    def _export_succeeded(self, report: object) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất thống kê", "thong-ke-bai-xe.csv", "CSV (*.csv)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(
                    [
                        "Nhóm khách hàng",
                        "Mã lượt",
                        "Biển số",
                        "Loại xe",
                        "Thời gian vào",
                        "Thời gian ra",
                        "Trạng thái hiện tại",
                    ]
                )
                for item in report:
                    group = "Đã đăng ký" if item.is_registered_customer else "Khách vãng lai"
                    values = [group, *self._row(item)]
                    # Prevent spreadsheet applications from interpreting data as formulas.
                    writer.writerow(
                        [
                            "'" + value
                            if value.lstrip().startswith(("=", "+", "-", "@"))
                            else value
                            for value in values
                        ]
                    )
        except OSError as exc:
            QMessageBox.critical(self, "Không thể xuất CSV", str(exc))
            return
        self._report = report
        self._update_report_tables()
        QMessageBox.information(self, "Xuất CSV", f"Đã xuất {len(report)} lượt xe.")

    def _export_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Không thể xuất thống kê", message)

    def _export_finished(self) -> None:
        worker = self.sender()
        if worker is not self._export_worker:
            return
        self._export_worker = None
        worker.deleteLater()
        self.export_button.setEnabled(True)
        self._emit_operations_idle()

    def has_running_operations(self) -> bool:
        return any(
            worker is not None and worker.isRunning()
            for worker in (self._refresh_worker, self._export_worker)
        )

    def _emit_operations_idle(self) -> None:
        if not self.has_running_operations() and not self._refresh_pending:
            self.operations_idle.emit()

    def _date_bounds(self) -> tuple[datetime | None, datetime | None]:
        from_text = self.from_date.text().strip()
        to_text = self.to_date.text().strip()
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
