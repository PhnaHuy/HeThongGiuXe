"""PySide6 Login Dialog and Window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from parking_app.application.auth_service import AuthService
from parking_app.domain.exceptions import AccountLockedError, AuthenticationError
from parking_app.domain.models import User


class LoginDialog(QDialog):
    """Modal login dialog capturing operator credentials."""

    authenticated = Signal(User)

    def __init__(self, auth_service: AuthService, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("loginDialog")
        self.auth_service = auth_service
        self.current_user: User | None = None

        self.setWindowTitle("Đăng nhập Hệ thống Quản lý Bãi xe")
        self.setFixedSize(460, 320)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(30, 26, 30, 26)

        # Header Title
        title_label = QLabel("HỆ THỐNG QUẢN LÝ BÃI GIỮ XE")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        sub_label = QLabel("Đăng nhập để tiếp tục vận hành hệ thống")
        sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_label.setStyleSheet("color: #666;")
        layout.addWidget(sub_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Form fields
        form = QFormLayout()
        form.setSpacing(10)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Nhập tên đăng nhập (vd: admin, nhanvien)")
        self.username_input.setFixedHeight(32)
        form.addRow("Tên đăng nhập:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Nhập mật khẩu")
        self.password_input.setFixedHeight(32)
        form.addRow("Mật khẩu:", self.password_input)

        layout.addLayout(form)

        # Error notification label
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("Đăng nhập")
        self.login_btn.setFixedHeight(36)
        self.login_btn.setStyleSheet(
            "background-color: #1976d2; color: white; font-weight: bold; border-radius: 4px;"
        )
        self.login_btn.clicked.connect(self._handle_login)
        btn_layout.addWidget(self.login_btn)

        self.cancel_btn = QPushButton("Thoát")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

        # Enter key triggers login
        self.password_input.returnPressed.connect(self._handle_login)
        self.username_input.returnPressed.connect(self._handle_login)

    def _handle_login(self) -> None:
        self.error_label.setText("")
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self.error_label.setText("Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.")
            return

        try:
            user = self.auth_service.authenticate(username, password)
            self.current_user = user
            self.authenticated.emit(user)
            self.accept()
        except AccountLockedError as e:
            self.error_label.setText(str(e))
        except AuthenticationError as e:
            self.error_label.setText(str(e))
        except Exception as e:
            self.error_label.setText(f"Lỗi hệ thống: {e}")
