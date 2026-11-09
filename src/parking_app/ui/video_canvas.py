"""Qt-owned image copy and parking-space polygon overlays with letterboxing."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from parking_app.domain.video import ParkingSpace, ParkingSpaceStatus
from parking_app.domain.vision import PlateDetection


def bgr_to_qimage(image) -> QImage:
    import cv2

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    # copy() detaches Qt storage before numpy memory goes out of scope.
    return QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()


class VideoCanvas(QWidget):
    polygon_changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.image = QImage()
        self.plate_detections: tuple[PlateDetection, ...] = ()
        self.parking_spaces: tuple[ParkingSpace, ...] = ()
        self.parking_space_states: dict[str, ParkingSpaceStatus] = {}
        self.polygon_editable = False
        self.pending_polygon: list[tuple[float, float]] = []
        self.message = "Chọn nguồn và nhấn Phát / Kết nối"

    def image_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        size = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF(
            (self.width() - size.width()) / 2,
            (self.height() - size.height()) / 2,
            size.width(),
            size.height(),
        )

    def set_image(
        self,
        image: QImage,
        parking_space_states: dict[str, ParkingSpaceStatus] | None = None,
        plate_detections: tuple[PlateDetection, ...] = (),
    ) -> None:
        self.image = image
        self.plate_detections = plate_detections
        self.parking_space_states = parking_space_states or {
            space.code: ParkingSpaceStatus.UNKNOWN for space in self.parking_spaces
        }
        self.update()

    def clear_image(self, message: str) -> None:
        self.image = QImage()
        self.plate_detections = ()
        self.parking_space_states = {
            space.code: ParkingSpaceStatus.UNKNOWN for space in self.parking_spaces
        }
        self.cancel_polygon()
        self.message = message
        self.update()

    def set_parking_spaces(self, spaces: tuple[ParkingSpace, ...]) -> None:
        self.parking_spaces = spaces
        self.parking_space_states = {space.code: ParkingSpaceStatus.UNKNOWN for space in spaces}
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#15202b"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.image.isNull():
            painter.setPen(QColor("#e1e8ed"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
            return
        rect = self.image_rect()
        painter.drawImage(rect, self.image)
        colors = {
            ParkingSpaceStatus.FREE: QColor(46, 204, 113, 70),
            ParkingSpaceStatus.OCCUPIED: QColor(231, 76, 60, 90),
            ParkingSpaceStatus.UNKNOWN: QColor(149, 165, 166, 75),
        }
        for space in self.parking_spaces:
            polygon = [
                QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())
                for x, y in space.points
            ]
            state = self.parking_space_states.get(space.code, ParkingSpaceStatus.UNKNOWN)
            painter.setBrush(colors[state])
            painter.setPen(QPen(colors[state].darker(150), 2))
            painter.drawPolygon(QPolygonF(polygon))
            center_x = sum(point.x() for point in polygon) / len(polygon)
            center_y = sum(point.y() for point in polygon) / len(polygon)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(QPointF(center_x, center_y), f"{space.code}: {state.value}")
        if self.pending_polygon:
            pending = [
                QPointF(rect.x() + x * rect.width(), rect.y() + y * rect.height())
                for x, y in self.pending_polygon
            ]
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#00e5ff"), 2, Qt.PenStyle.DashLine))
            if len(pending) > 1:
                painter.drawPolyline(QPolygonF(pending))
            for point in pending:
                painter.drawEllipse(point, 4, 4)
        painter.setPen(QPen(QColor("#ffb300"), 2))
        for detection in self.plate_detections:
            box = QRectF(
                rect.x() + detection.x1 * rect.width(),
                rect.y() + detection.y1 * rect.height(),
                (detection.x2 - detection.x1) * rect.width(),
                (detection.y2 - detection.y1) * rect.height(),
            )
            painter.drawRect(box)
            painter.drawText(
                box.topLeft() + QPointF(2, -4),
                f"Biển số {detection.confidence:.0%}",
            )

    def _normalized(self, position: QPointF) -> QPointF | None:
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(position):
            return None
        return QPointF(
            (position.x() - rect.x()) / rect.width(), (position.y() - rect.y()) / rect.height()
        )

    def mousePressEvent(self, event) -> None:
        if self.polygon_editable and event.button() == Qt.MouseButton.LeftButton:
            point = self._normalized(event.position())
            if point is not None:
                self.pending_polygon.append((point.x(), point.y()))
                self.update()
            return

    def begin_polygon(self) -> None:
        self.pending_polygon.clear()
        self.polygon_editable = True
        self.update()

    def finish_polygon(self) -> tuple[tuple[float, float], ...]:
        points = tuple(self.pending_polygon)
        self.pending_polygon.clear()
        self.polygon_editable = False
        self.update()
        self.polygon_changed.emit(points)
        return points

    def cancel_polygon(self) -> None:
        self.pending_polygon.clear()
        self.polygon_editable = False
        self.update()
