"""Customer and vehicle management UI view (NV-03, NV-04, M05)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parking_app.application.customer_service import CustomerService
from parking_app.domain.enums import UserRole, VehicleType
from parking_app.domain.exceptions import (
    DuplicateCustomerError,
    DuplicatePlateError,
    ValidationError,
)
from parking_app.domain.models import Customer, User, Vehicle
from parking_app.domain.plate import normalize_plate


class CustomerDialog(QDialog):
    """Dialog to create or update a customer record."""

    def __init__(
        self,
        customer_service: CustomerService,
        actor: User,
        customer: Customer | None = None,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.customer_service = customer_service
        self.actor = actor
        self.customer = customer
        self.result_customer: Customer | None = None

        self.setWindowTitle("Sửa thông tin khách hàng" if customer else "Thêm khách hàng mới")
        self.setFixedSize(420, 300)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("VD: KH0001")
        if self.customer:
            self.code_input.setText(self.customer.customer_code)
            self.code_input.setEnabled(False)  # Customer code is immutable after creation
        form.addRow("Mã khách hàng (*):", self.code_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Họ và tên khách hàng")
        if self.customer:
            self.name_input.setText(self.customer.full_name)
        form.addRow("Họ và tên (*):", self.name_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Số điện thoại liên hệ")
        if self.customer:
            self.phone_input.setText(self.customer.phone_number)
        form.addRow("Số điện thoại (*):", self.phone_input)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Ghi chú thêm (nếu có)")
        if self.customer and self.customer.note:
            self.note_input.setText(self.customer.note)
        form.addRow("Ghi chú:", self.note_input)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Lưu hồ sơ")
        self.save_btn.setStyleSheet("background-color: #2e7d32; color: white; font-weight: bold;")
        self.save_btn.clicked.connect(self._handle_save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Hủy bỏ")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def _handle_save(self) -> None:
        self.error_label.setText("")
        code = self.code_input.text().strip().upper()
        name = self.name_input.text().strip()
        phone = self.phone_input.text().strip()
        note = self.note_input.text().strip()

        try:
            if self.customer:
                saved = self.customer_service.update_customer(
                    actor=self.actor,
                    customer_id=self.customer.id,
                    full_name=name,
                    phone_number=phone,
                    note=note,
                )
            else:
                saved = self.customer_service.register_customer(
                    actor=self.actor,
                    customer_code=code,
                    full_name=name,
                    phone_number=phone,
                    note=note,
                )
            self.result_customer = saved
            self.accept()
        except (ValidationError, DuplicateCustomerError) as e:
            self.error_label.setText(str(e))
        except Exception as e:
            self.error_label.setText(f"Lỗi: {e}")


class VehicleDialog(QDialog):
    """Dialog to register a new vehicle for a customer."""

    def __init__(
        self,
        customer_service: CustomerService,
        actor: User,
        customer_id: int,
        parent=None,  # noqa: ANN001
        vehicle: Vehicle | None = None,
    ) -> None:
        super().__init__(parent)
        self.customer_service = customer_service
        self.actor = actor
        self.customer_id = customer_id
        self.vehicle = vehicle
        self.result_vehicle: Vehicle | None = None

        self.setWindowTitle(
            "Sửa thông tin phương tiện" if vehicle else "Đăng ký phương tiện cho khách hàng"
        )
        self.setFixedSize(450, 280)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)

        self.plate_input = QLineEdit()
        self.plate_input.setPlaceholderText("VD: 51F-123.45 hoặc 29A 888.88")
        if self.vehicle:
            self.plate_input.setText(self.vehicle.display_plate)
        self.plate_input.textChanged.connect(self._on_plate_text_changed)
        form.addRow("Biển số xe (*):", self.plate_input)

        self.norm_preview_label = QLabel("Biển số chuẩn hóa: (chưa nhập)")
        self.norm_preview_label.setStyleSheet("color: #0277bd; font-weight: bold;")
        form.addRow("", self.norm_preview_label)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Xe máy", VehicleType.MOTORCYCLE)
        self.type_combo.addItem("Ô tô", VehicleType.CAR)
        if self.vehicle:
            self.type_combo.setCurrentIndex(self.type_combo.findData(self.vehicle.vehicle_type))
        form.addRow("Loại phương tiện:", self.type_combo)

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Màu xe, hãng xe, v.v.")
        if self.vehicle:
            self.note_input.setText(self.vehicle.note or "")
        form.addRow("Ghi chú xe:", self.note_input)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: red;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Lưu thay đổi" if self.vehicle else "Đăng ký xe")
        self.save_btn.setStyleSheet("background-color: #1976d2; color: white; font-weight: bold;")
        self.save_btn.clicked.connect(self._handle_save)
        btn_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Hủy bỏ")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def _on_plate_text_changed(self, text: str) -> None:
        norm = normalize_plate(text)
        if norm:
            self.norm_preview_label.setText(f"Biển số chuẩn hóa: {norm}")
        else:
            self.norm_preview_label.setText("Biển số chuẩn hóa: (chưa nhập)")

    def _handle_save(self) -> None:
        self.error_label.setText("")
        raw_plate = self.plate_input.text().strip()
        v_type = VehicleType(self.type_combo.currentData())
        note = self.note_input.text().strip()

        try:
            if self.vehicle:
                if self.vehicle.id is None:
                    raise ValidationError("Không xác định được phương tiện cần sửa.")
                saved = self.customer_service.update_vehicle(
                    actor=self.actor,
                    vehicle_id=self.vehicle.id,
                    raw_plate=raw_plate,
                    vehicle_type=v_type,
                    note=note,
                )
            else:
                saved = self.customer_service.register_vehicle(
                    actor=self.actor,
                    customer_id=self.customer_id,
                    raw_plate=raw_plate,
                    vehicle_type=v_type,
                    note=note,
                )
            self.result_vehicle = saved
            self.accept()
        except DuplicatePlateError as e:
            self.error_label.setText(f"CẢNH BÁO TRÙNG BIỂN SỐ:\n{e}")
        except ValidationError as e:
            self.error_label.setText(str(e))
        except Exception as e:
            self.error_label.setText(f"Lỗi: {e}")


class CustomerManagementWidget(QWidget):
    """Main view for customer and multi-vehicle registry."""

    def __init__(
        self,
        customer_service: CustomerService,
        current_user: User,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self.customer_service = customer_service
        self.current_user = current_user
        self.selected_customer: Customer | None = None

        self._init_ui()
        self.refresh_customer_list()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # Search Bar and Top Actions
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Tìm kiếm khách hàng:"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Nhập mã khách, họ tên, số điện thoại hoặc biển số...")
        self.search_input.returnPressed.connect(self._on_search)
        search_layout.addWidget(self.search_input)

        self.search_btn = QPushButton("Tìm kiếm")
        self.search_btn.clicked.connect(self._on_search)
        search_layout.addWidget(self.search_btn)

        self.all_btn = QPushButton("Tất cả")
        self.all_btn.clicked.connect(self._on_reset_search)
        search_layout.addWidget(self.all_btn)

        search_layout.addSpacing(20)

        self.add_customer_btn = QPushButton("+ Thêm khách hàng")
        self.add_customer_btn.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 6px 12px;"
        )
        self.add_customer_btn.clicked.connect(self._on_add_customer)
        search_layout.addWidget(self.add_customer_btn)

        main_layout.addLayout(search_layout)

        # Splitter: Left = Customers Table, Right = Customer Details & Vehicles
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left Widget: Customer Table
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel("<b>Danh sách hồ sơ khách hàng:</b>"))
        self.customer_table = QTableWidget()
        self.customer_table.setColumnCount(5)
        self.customer_table.setHorizontalHeaderLabels(
            ["Mã khách", "Họ và tên", "Số điện thoại", "Số xe", "Ghi chú"]
        )
        self.customer_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.customer_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.customer_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.customer_table.itemSelectionChanged.connect(self._on_customer_selected)
        left_layout.addWidget(self.customer_table)

        splitter.addWidget(left_widget)

        # Right Widget: Selected Customer Details & Vehicles
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Customer Detail Box
        self.detail_group = QGroupBox("Chi tiết khách hàng")
        detail_layout = QVBoxLayout(self.detail_group)

        self.detail_info_label = QLabel("Vui lòng chọn một khách hàng từ bảng bên trái.")
        self.detail_info_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_info_label)

        detail_btn_layout = QHBoxLayout()
        self.edit_cust_btn = QPushButton("Sửa thông tin khách")
        self.edit_cust_btn.setEnabled(False)
        self.edit_cust_btn.clicked.connect(self._on_edit_customer)
        detail_btn_layout.addWidget(self.edit_cust_btn)
        detail_layout.addLayout(detail_btn_layout)

        right_layout.addWidget(self.detail_group)

        # Vehicles Box
        vehicles_group = QGroupBox("Danh sách phương tiện đã đăng ký (Một khách nhiều xe)")
        veh_layout = QVBoxLayout(vehicles_group)

        self.vehicle_table = QTableWidget()
        self.vehicle_table.setColumnCount(5)
        self.vehicle_table.setHorizontalHeaderLabels(
            ["ID", "Biển số hiển thị", "Biển số chuẩn hóa", "Loại xe", "Ghi chú"]
        )
        self.vehicle_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.vehicle_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.vehicle_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        veh_layout.addWidget(self.vehicle_table)

        veh_btn_layout = QHBoxLayout()
        self.add_vehicle_btn = QPushButton("+ Đăng ký thêm xe")
        self.add_vehicle_btn.setEnabled(False)
        self.add_vehicle_btn.setStyleSheet(
            "background-color: #1976d2; color: white; font-weight: bold; padding: 5px 10px;"
        )
        self.add_vehicle_btn.clicked.connect(self._on_add_vehicle)
        veh_btn_layout.addWidget(self.add_vehicle_btn)

        self.delete_vehicle_btn = QPushButton("Xóa xe chọn")
        self.delete_vehicle_btn.setEnabled(False)
        self.delete_vehicle_btn.clicked.connect(self._on_delete_vehicle)
        veh_btn_layout.addWidget(self.delete_vehicle_btn)

        self.edit_vehicle_btn = QPushButton("Sửa xe chọn")
        self.edit_vehicle_btn.setEnabled(False)
        self.edit_vehicle_btn.clicked.connect(self._on_edit_vehicle)
        if self.current_user.role == UserRole.ADMIN:
            veh_btn_layout.addWidget(self.edit_vehicle_btn)

        veh_layout.addLayout(veh_btn_layout)
        right_layout.addWidget(vehicles_group)

        splitter.addWidget(right_widget)
        splitter.setSizes([500, 500])
        main_layout.addWidget(splitter)

    def refresh_customer_list(self, query: str = "") -> None:
        customers = self.customer_service.search_customers(query)
        self.customer_table.setRowCount(len(customers))
        for row, cust in enumerate(customers):
            # Store customer ID in first column user role
            item_code = QTableWidgetItem(cust.customer_code)
            item_code.setData(Qt.ItemDataRole.UserRole, cust.id)
            self.customer_table.setItem(row, 0, item_code)
            self.customer_table.setItem(row, 1, QTableWidgetItem(cust.full_name))
            self.customer_table.setItem(row, 2, QTableWidgetItem(cust.phone_number))
            self.customer_table.setItem(row, 3, QTableWidgetItem(str(len(cust.vehicles))))
            self.customer_table.setItem(row, 4, QTableWidgetItem(cust.note or ""))

    def _on_search(self) -> None:
        query = self.search_input.text().strip()
        self.refresh_customer_list(query)

    def _on_reset_search(self) -> None:
        self.search_input.clear()
        self.refresh_customer_list()

    def _on_add_customer(self) -> None:
        dialog = CustomerDialog(self.customer_service, self.current_user, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_customer_list()

    def _on_edit_customer(self) -> None:
        if not self.selected_customer or self.current_user.role != UserRole.ADMIN:
            return
        dialog = CustomerDialog(
            self.customer_service,
            self.current_user,
            customer=self.selected_customer,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_customer_list()
            self._load_customer_details(self.selected_customer.id)

    def _on_customer_selected(self) -> None:
        selected_rows = self.customer_table.selectionModel().selectedRows()
        if not selected_rows:
            self.selected_customer = None
            self.edit_cust_btn.setEnabled(False)
            self.add_vehicle_btn.setEnabled(False)
            self.delete_vehicle_btn.setEnabled(False)
            self.edit_vehicle_btn.setEnabled(False)
            self.detail_info_label.setText("Vui lòng chọn một khách hàng từ bảng bên trái.")
            self.vehicle_table.setRowCount(0)
            return

        row = selected_rows[0].row()
        item = self.customer_table.item(row, 0)
        if item:
            cust_id = item.data(Qt.ItemDataRole.UserRole)
            self._load_customer_details(cust_id)

    def _load_customer_details(self, customer_id: int) -> None:
        customer = self.customer_service.get_customer(customer_id)
        if not customer:
            return

        self.selected_customer = customer
        self.edit_cust_btn.setEnabled(self.current_user.role == UserRole.ADMIN)
        self.add_vehicle_btn.setEnabled(True)
        self.delete_vehicle_btn.setEnabled(bool(customer.vehicles))
        self.edit_vehicle_btn.setEnabled(
            self.current_user.role == UserRole.ADMIN and bool(customer.vehicles)
        )

        self.detail_info_label.setText(
            f"<b>Mã khách:</b> {customer.customer_code}<br>"
            f"<b>Họ và tên:</b> {customer.full_name}<br>"
            f"<b>Số điện thoại:</b> {customer.phone_number}<br>"
            f"<b>Ghi chú:</b> {customer.note or 'Không có'}"
        )

        # Load Vehicles
        self.vehicle_table.setRowCount(len(customer.vehicles))
        for r, veh in enumerate(customer.vehicles):
            item_id = QTableWidgetItem(str(veh.id))
            item_id.setData(Qt.ItemDataRole.UserRole, veh.id)
            self.vehicle_table.setItem(r, 0, item_id)
            self.vehicle_table.setItem(r, 1, QTableWidgetItem(veh.display_plate))
            self.vehicle_table.setItem(r, 2, QTableWidgetItem(veh.normalized_plate))
            self.vehicle_table.setItem(r, 3, QTableWidgetItem(veh.vehicle_type.display_name))
            self.vehicle_table.setItem(r, 4, QTableWidgetItem(veh.note or ""))

    def _on_add_vehicle(self) -> None:
        if not self.selected_customer:
            return
        dialog = VehicleDialog(
            self.customer_service,
            self.current_user,
            customer_id=self.selected_customer.id,
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_customer_details(self.selected_customer.id)
            self.refresh_customer_list(self.search_input.text().strip())

    def _on_edit_vehicle(self) -> None:
        if not self.selected_customer or self.current_user.role != UserRole.ADMIN:
            return
        selected_rows = self.vehicle_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn phương tiện cần sửa.")
            return
        row = selected_rows[0].row()
        item = self.vehicle_table.item(row, 0)
        vehicle_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        vehicle = next(
            (
                registered
                for registered in self.selected_customer.vehicles
                if registered.id == vehicle_id
            ),
            None,
        )
        if vehicle is None:
            QMessageBox.warning(self, "Không tìm thấy xe", "Hãy tải lại hồ sơ khách hàng.")
            return
        dialog = VehicleDialog(
            self.customer_service,
            self.current_user,
            customer_id=self.selected_customer.id,
            parent=self,
            vehicle=vehicle,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._load_customer_details(self.selected_customer.id)
            self.refresh_customer_list(self.search_input.text().strip())

    def _on_delete_vehicle(self) -> None:
        if not self.selected_customer:
            return
        selected_rows = self.vehicle_table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn xe cần xóa.")
            return

        row = selected_rows[0].row()
        item = self.vehicle_table.item(row, 0)
        plate_item = self.vehicle_table.item(row, 1)
        veh_id = item.data(Qt.ItemDataRole.UserRole)
        plate_str = plate_item.text() if plate_item else ""

        reply = QMessageBox.question(
            self,
            "Xác nhận xóa phương tiện",
            f"Bạn có chắc chắn muốn xóa xe biển số '{plate_str}' khỏi hồ sơ khách hàng không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.customer_service.delete_vehicle(
                self.current_user, veh_id, reason="Xóa qua giao diện quản lý"
            )
            self._load_customer_details(self.selected_customer.id)
            self.refresh_customer_list(self.search_input.text().strip())
