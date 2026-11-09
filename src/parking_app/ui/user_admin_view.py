"""User Account Administration UI View (QT-01)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
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

from parking_app.application.auth_service import AuthService
from parking_app.domain.enums import UserRole, UserStatus
from parking_app.domain.exceptions import DuplicateUserError, ValidationError
from parking_app.domain.models import User


class CreateUserDialog(QDialog):
    """Dialog to create a new system operator account."""

    def __init__(self, auth_service: AuthService, actor: User, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.auth_service = auth_service
        self.actor = actor
        self.result_user: User | None = None

        self.setWindowTitle("Tạo tài khoản người dùng mới")
        self.setFixedSize(420, 300)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("VD: nhanvien2")
        form.addRow("Tên đăng nhập (*):", self.username_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Họ và tên đầy đủ")
        form.addRow("Họ và tên (*):", self.name_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Tối thiểu 6 ký tự")
        form.addRow("Mật khẩu (*):", self.password_input)

        self.role_combo = QComboBox()
        self.role_combo.addItem("Nhân viên vận hành", UserRole.STAFF)
        self.role_combo.addItem("Người quản lý", UserRole.MANAGER)
        self.role_combo.addItem("Quản trị viên", UserRole.ADMIN)
        form.addRow("Vai trò:", self.role_combo)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Tạo tài khoản")
        self.save_btn.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold;")
        self.save_btn.clicked.connect(self._handle_save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Hủy bỏ")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def _handle_save(self) -> None:
        self.error_label.setText("")
        username = self.username_input.text().strip().lower()
        name = self.name_input.text().strip()
        pwd = self.password_input.text()
        role = UserRole(self.role_combo.currentData())

        try:
            saved = self.auth_service.create_user(
                actor=self.actor,
                username=username,
                plain_password=pwd,
                full_name=name,
                role=role,
            )
            self.result_user = saved
            self.accept()
        except (ValidationError, DuplicateUserError) as e:
            self.error_label.setText(str(e))
        except Exception as e:
            self.error_label.setText(f"Lỗi: {e}")


class UserManagementWidget(QWidget):
    """Widget for managing operator accounts and security state."""

    def __init__(self, auth_service: AuthService, current_user: User, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.auth_service = auth_service
        self.current_user = current_user

        self._init_ui()
        self.refresh_user_list()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header Actions
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("<b>Danh sách tài khoản hệ thống:</b>"))
        top_layout.addStretch()

        self.add_user_btn = QPushButton("+ Tạo tài khoản mới")
        self.add_user_btn.setStyleSheet(
            "background-color: #1976d2; color: white; font-weight: bold; padding: 6px 12px;"
        )
        self.add_user_btn.clicked.connect(self._on_add_user)
        top_layout.addWidget(self.add_user_btn)

        self.toggle_status_btn = QPushButton("Khóa / Mở khóa tài khoản")
        self.toggle_status_btn.clicked.connect(self._on_toggle_status)
        top_layout.addWidget(self.toggle_status_btn)

        layout.addLayout(top_layout)

        # Users Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Tên đăng nhập", "Họ và tên", "Vai trò", "Trạng thái"]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

    def refresh_user_list(self) -> None:
        try:
            users = self.auth_service.list_users(self.current_user, include_locked=True)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi phân quyền", str(e))
            return

        self.table.setRowCount(len(users))
        for row, u in enumerate(users):
            item_id = QTableWidgetItem(str(u.id))
            item_id.setData(Qt.ItemDataRole.UserRole, u)
            self.table.setItem(row, 0, item_id)
            self.table.setItem(row, 1, QTableWidgetItem(u.username))
            self.table.setItem(row, 2, QTableWidgetItem(u.full_name))
            self.table.setItem(row, 3, QTableWidgetItem(u.role.display_name))

            status_item = QTableWidgetItem(u.status.display_name)
            if u.status == UserStatus.LOCKED:
                status_item.setForeground(Qt.GlobalColor.red)
            else:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            self.table.setItem(row, 4, status_item)

    def _on_add_user(self) -> None:
        dialog = CreateUserDialog(self.auth_service, self.current_user, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_user_list()

    def _on_toggle_status(self) -> None:
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(
                self, "Thông báo", "Vui lòng chọn tài khoản cần thay đổi trạng thái."
            )
            return

        row = selected_rows[0].row()
        item = self.table.item(row, 0)
        target_user: User = item.data(Qt.ItemDataRole.UserRole)

        new_status = (
            UserStatus.LOCKED if target_user.status == UserStatus.ACTIVE else UserStatus.ACTIVE
        )
        action_name = "KHÓA" if new_status == UserStatus.LOCKED else "MỞ KHÓA"

        confirm_msg = (
            f"Bạn có chắc chắn muốn {action_name.lower()} tài khoản "
            f"'{target_user.username}' ({target_user.full_name})?"
        )
        reply = QMessageBox.question(
            self,
            f"Xác nhận {action_name}",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.auth_service.set_user_status(
                    actor=self.current_user,
                    target_user_id=target_user.id,
                    status=new_status,
                    reason=f"{action_name} qua giao diện quản trị",
                )
                self.refresh_user_list()
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", str(e))
