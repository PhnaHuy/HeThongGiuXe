"""Application launcher and lifecycle controller."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.source_service import SourceService
from parking_app.config.settings import AppSettings, seed_initial_accounts
from parking_app.domain.models import User
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.infrastructure.persistence.database import (
    DatabaseSessionManager,
    create_sqlite_engine,
)
from parking_app.ui.login_window import LoginDialog
from parking_app.ui.main_window import MainWindow
from parking_app.ui.theme import install_app_theme


class ParkingApplication:
    """Desktop application controller managing login cycle and main window."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.settings = AppSettings()
        if db_path is not None:
            self.settings.db_path = Path(db_path)
        self.settings.ensure_directories()

        self.engine = create_sqlite_engine(self.settings.db_path)
        self.session_manager = DatabaseSessionManager(self.engine)
        self.session_manager.init_tables()
        seed_initial_accounts(self.session_manager)

        self.auth_service = AuthService(self.session_manager)
        self.customer_service = CustomerService(self.session_manager)
        self.audit_service = AuditService(self.session_manager)
        self.source_service = SourceService(self.session_manager)
        self.parking_service = ParkingService(
            self.session_manager,
            EvidenceStorage(self.settings.evidence_dir),
        )

        self.main_window: MainWindow | None = None

    def run(self) -> int:
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        app.setApplicationName("Hệ thống quản lý bãi giữ xe")
        install_app_theme(app)
        app.setQuitOnLastWindowClosed(False)
        QTimer.singleShot(0, self._show_login)
        return app.exec()

    def _show_login(self) -> None:
        login_dialog = LoginDialog(self.auth_service)
        login_dialog.authenticated.connect(self._on_authenticated)
        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            QApplication.quit()

    def _on_authenticated(self, user: User) -> None:
        self.main_window = MainWindow(
            current_user=user,
            auth_service=self.auth_service,
            customer_service=self.customer_service,
            audit_service=self.audit_service,
            parking_service=self.parking_service,
            source_service=self.source_service,
            video_options=self.settings.video_options,
            vision_options=self.settings.vision_options,
        )
        self.main_window.logout_requested.connect(
            self._show_login, Qt.ConnectionType.QueuedConnection
        )
        self.main_window.window_closed.connect(QApplication.quit)
        self.main_window.show()


def main() -> int:
    app_controller = ParkingApplication()
    return app_controller.run()


if __name__ == "__main__":
    raise SystemExit(main())
