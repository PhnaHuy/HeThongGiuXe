"""G8 application theme and release-window smoke checks."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from parking_app.application.audit_service import AuditService
from parking_app.application.auth_service import AuthService
from parking_app.application.customer_service import CustomerService
from parking_app.application.parking_service import ParkingService
from parking_app.application.source_service import SourceService
from parking_app.infrastructure.evidence.storage import EvidenceStorage
from parking_app.ui.login_window import LoginDialog
from parking_app.ui.main_window import MainWindow
from parking_app.ui.source_view import SourceManagementWidget
from parking_app.ui.theme import APP_STYLESHEET, install_app_theme


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    install_app_theme(app)
    return app


def test_styled_main_window_renders_role_tabs_and_header(
    qapp, session_manager, seeded_users, tmp_path
):
    parking = ParkingService(session_manager, EvidenceStorage(tmp_path / "evidence"))
    window = MainWindow(
        seeded_users["manager"],
        AuthService(session_manager),
        CustomerService(session_manager),
        AuditService(session_manager),
        parking_service=parking,
        source_service=SourceService(session_manager),
    )
    try:
        window.show()
        qapp.processEvents()
        assert window.windowTitle() == "Bãi xe thông minh — Quản lý vận hành"
        assert window.findChild(QWidget, "appHeader") is not None
        assert "Nguồn hình — Camera / MP4" in [
            window.tabs.tabText(index) for index in range(window.tabs.count())
        ]
        assert "Tổng quan và thống kê" in [
            window.tabs.tabText(index) for index in range(window.tabs.count())
        ]
        assert window.logout_btn.objectName() == "dangerButton"
        assert window.statusBar().currentMessage().startswith("AI chỉ đưa ra đề xuất")
    finally:
        window.close()


def test_source_editor_scrolls_and_form_controls_do_not_overlap(
    qapp, session_manager, seeded_users
):
    widget = SourceManagementWidget(SourceService(session_manager), seeded_users["admin"])
    widget.resize(1000, 620)
    widget.show()
    qapp.processEvents()
    try:
        assert widget.editor_scroll_area.isVisible()
        assert widget.editor.width() >= 340
        assert widget.canvas.geometry().right() < widget.editor.geometry().left()
        assert widget.save_button.isVisible()
        assert not widget.editor_scroll_area.isAncestorOf(widget.save_button)
        assert widget.create_source_button.isVisible()

        children = [
            child
            for child in widget.editor.findChildren(QWidget)
            if child.isVisible() and child.parentWidget() is widget.editor
        ]
        for index, first in enumerate(children):
            for second in children[index + 1 :]:
                assert not first.geometry().intersects(second.geometry()), (
                    first.objectName() or first.metaObject().className(),
                    second.objectName() or second.metaObject().className(),
                )
    finally:
        widget.close()


def test_create_source_has_feedback_and_saves_from_pinned_action(
    qapp, session_manager, seeded_users
):
    service = SourceService(session_manager)
    widget = SourceManagementWidget(service, seeded_users["admin"])
    widget.resize(1000, 620)
    widget.show()
    qapp.processEvents()
    try:
        widget.create_source_button.click()
        assert widget.source_feedback_label.text().startswith("Tạo nguồn mới:")
        assert widget.sources.currentIndex() == 0
        assert widget.name_input.text() == ""
        assert widget.save_button.isVisible()

        widget.name_input.setText("Cổng Bắc")
        widget.endpoint_input.setText("0")
        widget.save_button.click()
        qapp.processEvents()

        stored = service.list_sources(seeded_users["admin"])
        assert len(stored) == 1
        assert stored[0].name == "Cổng Bắc"
        assert widget.sources.currentData().id == stored[0].id
        assert widget.delete_source_button.isEnabled()
        assert "Đã lưu và chọn nguồn" in widget.source_feedback_label.text()
    finally:
        widget.close()


def test_shared_theme_installs_consistent_desktop_style(qapp):
    install_app_theme(qapp)

    assert qapp.font().family() == "Segoe UI"
    assert qapp.font().pointSize() == 10
    assert qapp.styleSheet() == APP_STYLESHEET
    for selector in (
        "QMainWindow",
        "QTabWidget::pane",
        "QPushButton:hover",
        "QLineEdit:focus",
        "QTableWidget",
        "QStatusBar",
    ):
        assert selector in APP_STYLESHEET


def test_theme_can_be_installed_repeatedly(qapp):
    install_app_theme(qapp)
    first_stylesheet = qapp.styleSheet()
    install_app_theme(qapp)

    assert qapp.styleSheet() == first_stylesheet


def test_login_dialog_hides_sample_password_hint(qapp, session_manager):
    dialog = LoginDialog(AuthService(session_manager))
    try:
        assert dialog.height() == 320
        assert not any(
            "Tài khoản mẫu" in label.text() or "admin123" in label.text()
            for label in dialog.findChildren(QWidget)
            if hasattr(label, "text")
        )
    finally:
        dialog.close()
