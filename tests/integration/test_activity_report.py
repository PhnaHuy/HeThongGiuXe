import time
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest

from parking_app.application.parking_service import ParkingService
from parking_app.domain.enums import ParkingStatus, VehicleType
from parking_app.domain.exceptions import PermissionDeniedError, ValidationError
from parking_app.infrastructure.persistence.orm_models import ParkingSessionModel


def test_report_includes_entry_or_exit_and_preserves_customer_category(
    session_manager, seeded_users
):
    start = datetime(2026, 1, 2, tzinfo=UTC)
    end = start + timedelta(days=1)
    with session_manager.session() as db:
        for code, entry, exit_time, registered in [
            ("entry", start, None, True),
            ("exit", start - timedelta(days=1), start, False),
            ("both", start, start + timedelta(hours=1), False),
            ("outside", end, None, True),
        ]:
            db.add(
                ParkingSessionModel(
                    session_code=code,
                    snapshot_plate=code.upper(),
                    snapshot_display_plate=code,
                    snapshot_vehicle_type=VehicleType.CAR,
                    is_registered_customer=registered,
                    entry_time=entry,
                    exit_time=exit_time,
                    status=ParkingStatus.DA_RA if exit_time else ParkingStatus.DANG_GUI,
                )
            )
    service = ParkingService(session_manager, None)
    report = service.get_activity_report(seeded_users["admin"], start, end)
    assert {item.session_code for item in report} == {"entry", "exit", "both"}
    assert {item.session_code for item in report if item.is_registered_customer} == {"entry"}
    with pytest.raises(PermissionDeniedError):
        service.get_activity_report(seeded_users["staff"], start, end)
    with pytest.raises(ValidationError):
        service.get_activity_report(seeded_users["admin"], end, start)


def test_csv_export_contains_both_customer_groups(session_manager, seeded_users, monkeypatch):
    import csv
    import os
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from parking_app.ui.dashboard_view import ParkingDashboardWidget

    app = QApplication.instance() or QApplication([])
    with session_manager.session() as db:
        for code, registered in [("registered", True), ("guest", False)]:
            db.add(
                ParkingSessionModel(
                    session_code=code,
                    snapshot_plate=code.upper(),
                    snapshot_display_plate=code,
                    snapshot_vehicle_type=VehicleType.CAR,
                    is_registered_customer=registered,
                    entry_time=datetime(2026, 1, 2, tzinfo=UTC),
                    status=ParkingStatus.DANG_GUI,
                )
            )
    service = ParkingService(session_manager, None)
    widget = ParkingDashboardWidget(service, seeded_users["admin"])
    widget.from_date.setText("2026-01-01")
    widget.to_date.setText("2026-01-03")
    widget.refresh()
    deadline = time.monotonic() + 5
    while widget._refresh_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert widget.registered_table.rowCount() == widget.guest_table.rowCount() == 1

    class Output(StringIO):
        def close(self):
            self.saved = self.getvalue()
            super().close()

    output = Output()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: ("report.csv", ""))
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: output)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    widget._export_csv()
    deadline = time.monotonic() + 5
    while widget._export_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    rows = list(csv.reader(StringIO(output.saved)))
    assert len(rows) == 3
    assert {row[1] for row in rows[1:]} == {"registered", "guest"}
    assert len(rows[0]) == 7
    widget.close()
    assert app is not None
