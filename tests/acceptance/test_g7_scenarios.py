"""G7 polygon editor, parking summaries, and independent session comparison."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from parking_app.application.source_service import SourceService
from parking_app.domain.video import (
    ParkingSpace,
    ParkingSpaceStatus,
    SourceConfig,
    SourceKind,
    SourcePurpose,
)
from parking_app.infrastructure.persistence.orm_models import AuditLogModel
from parking_app.ui.source_view import SourceManagementWidget
from parking_app.ui.video_canvas import bgr_to_qimage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_polygon_editor_and_source_persistence(qapp, session_manager, seeded_users):
    service = SourceService(session_manager)
    widget = SourceManagementWidget(service, seeded_users["admin"])
    config = SourceConfig(
        "lot-camera",
        "Khu A",
        SourceKind.LIVE,
        "0",
        purpose=SourcePurpose.PARKING,
    )
    widget._load_config(config)
    widget.canvas.resize(480, 270)
    widget.canvas.set_image(bgr_to_qimage(np.zeros((90, 160, 3), np.uint8)))
    widget.space_code_input.setText("A01")
    widget._begin_polygon()
    rect = widget.canvas.image_rect()
    for x, y in ((0.1, 0.1), (0.8, 0.1), (0.8, 0.8), (0.1, 0.8)):
        point = QPoint(int(rect.x() + rect.width() * x), int(rect.y() + rect.height() * y))
        QTest.mouseClick(widget.canvas, Qt.MouseButton.LeftButton, pos=point)
    widget.canvas.grab()
    widget.canvas.finish_polygon()
    widget._save_source()

    try:
        stored = service.list_sources(seeded_users["admin"])[0]
        assert stored.parking_spaces[0].code == "A01"
        assert len(stored.parking_spaces[0].points) == 4
        with session_manager.session() as session:
            audit = session.query(AuditLogModel).filter_by(target_id="lot-camera").one()
            assert audit.new_values["parking_spaces"][0]["code"] == "A01"
    finally:
        widget.close()


def test_losing_preview_cancels_polygon_draft(qapp, session_manager, seeded_users):
    widget = SourceManagementWidget(SourceService(session_manager), seeded_users["admin"])
    try:
        widget._load_config(
            SourceConfig(
                "lot-camera",
                "Khu A",
                SourceKind.LIVE,
                "0",
                purpose=SourcePurpose.PARKING,
            )
        )
        widget.canvas.set_image(bgr_to_qimage(np.zeros((90, 160, 3), np.uint8)))
        widget.space_code_input.setText("A01")
        widget._begin_polygon()
        rect = widget.canvas.image_rect()
        point = QPoint(int(rect.x() + rect.width() * 0.2), int(rect.y() + rect.height() * 0.2))
        QTest.mouseClick(widget.canvas, Qt.MouseButton.LeftButton, pos=point)

        widget._clear_image("Camera disconnected")

        assert widget._active_polygon_code is None
        assert not widget.canvas.polygon_editable
        assert widget.canvas.editable
        assert not widget.finish_polygon_button.isEnabled()
    finally:
        widget.close()


def test_parking_summary_shows_unknown_after_image_loss_and_keeps_counts_separate(
    qapp, session_manager, seeded_users
):
    widget = SourceManagementWidget(
        SourceService(session_manager),
        seeded_users["admin"],
        open_session_count_provider=lambda: 3,
    )
    config = SourceConfig(
        "lot-camera",
        "Khu A",
        SourceKind.LIVE,
        "0",
        purpose=SourcePurpose.PARKING,
        parking_spaces=(
            ParkingSpace("A01", ((0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4))),
            ParkingSpace("A02", ((0.5, 0.1), (0.9, 0.1), (0.9, 0.4), (0.5, 0.4))),
        ),
    )
    widget._load_config(config)
    try:
        widget.canvas.set_image(
            bgr_to_qimage(np.zeros((90, 160, 3), np.uint8)),
            parking_space_states={
                "A01": ParkingSpaceStatus.OCCUPIED,
                "A02": ParkingSpaceStatus.FREE,
            },
        )
        widget._render_parking_summary()
        assert "Có xe: 1" in widget.parking_summary_label.text()
        assert "Lượt đang gửi toàn bãi (đếm riêng): 3" in widget.parking_summary_label.text()

        widget.canvas.clear_image("Camera disconnected")
        widget._render_parking_summary()
        summary = widget.parking_summary_label.text()
        assert "Không xác định: 2" in summary
        assert "chưa thể đối chiếu đầy đủ" in summary
    finally:
        widget.close()
