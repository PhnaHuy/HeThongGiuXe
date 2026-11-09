"""Qt-owned image copy and normalized gate-line drawing with letterboxing."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from parking_app.domain.video import GateLine, ParkingSpace, ParkingSpaceStatus
from parking_app.domain.vision import VehicleDetection


def bgr_to_qimage(image) -> QImage:
    import cv2

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width, _ = rgb.shape
    # copy() detaches Qt storage before numpy memory goes out of scope.
    return QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888).copy()


class VideoCanvas(QWidget):
    line_changed = Signal(object)
    polygon_changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.image = QImage()
        self.line: GateLine | None = None
        self.detections: tuple[VehicleDetection, ...] = ()
        self.parking_spaces: tuple[ParkingSpace, ...] = ()
        self.parking_space_states: dict[str, ParkingSpaceStatus] = {}
        self.polygon_editable = False
        self.pending_polygon: list[tuple[float, float]] = []
        self._polygon_previous_editable = False
        self.editable = False
        self.message = "Chọn nguồn và nhấn Phát / Kết nối"
        self._start: QPointF | None = None

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
        detections: tuple[VehicleDetection, ...] = (),
        parking_space_states: dict[str, ParkingSpaceStatus] | None = None,
    ) -> None:
        self.image = image
        self.detections = detections
        self.parking_space_states = parking_space_states or {
            space.code: ParkingSpaceStatus.UNKNOWN for space in self.parking_spaces
        }
        self.update()

    def clear_image(self, message: str) -> None:
        self.image = QImage()
        self.detections = ()
        self.parking_space_states = {
            space.code: ParkingSpaceStatus.UNKNOWN for space in self.parking_spaces
        }
        self._start = None
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
        painter.setPen(QPen(QColor("#00e676"), 2))
        for detection in self.detections:
            box = QRectF(
                rect.x() + detection.x1 * rect.width(),
                rect.y() + detection.y1 * rect.height(),
                (detection.x2 - detection.x1) * rect.width(),
                (detection.y2 - detection.y1) * rect.height(),
            )
            painter.drawRect(box)
            label = f"{detection.vehicle_type.display_name} {detection.confidence:.0%}"
            if detection.track_id is not None:
                label += f" | #{detection.track_id}"
            painter.drawText(box.topLeft() + QPointF(2, -4), label)
        if self.line is None:
            return
        line = self.line
        a = QPointF(rect.x() + line.x1 * rect.width(), rect.y() + line.y1 * rect.height())
        b = QPointF(rect.x() + line.x2 * rect.width(), rect.y() + line.y2 * rect.height())
        painter.setPen(QPen(QColor("#ffe066"), 3))
        painter.drawLine(a, b)
        painter.drawText(a, "A")
        painter.drawText(b, "B")
        mid = (a + b) / 2
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length > 0:
            sign = 1 if line.entry_positive else -1
            normal = QPointF(-dy / length * sign, dx / length * sign)
            tip = mid + normal * 35
            painter.drawLine(mid - normal * 25, tip)
            tangent = QPointF(dx / length, dy / length)
            painter.drawLine(tip, tip - normal * 10 + tangent * 6)
            painter.drawLine(tip, tip - normal * 10 - tangent * 6)
            painter.drawText(tip + QPointF(5, 0), "VÀO")

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
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            self._start = self._normalized(event.position())

    def begin_polygon(self) -> None:
        self.pending_polygon.clear()
        self._polygon_previous_editable = self.editable
        self.polygon_editable = True
        self.editable = False
        self.update()

    def finish_polygon(self) -> tuple[tuple[float, float], ...]:
        points = tuple(self.pending_polygon)
        self.pending_polygon.clear()
        self.polygon_editable = False
        self.editable = self._polygon_previous_editable
        self.update()
        self.polygon_changed.emit(points)
        return points

    def cancel_polygon(self) -> None:
        self.pending_polygon.clear()
        if self.polygon_editable:
            self.editable = self._polygon_previous_editable
        self.polygon_editable = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        end = self._normalized(event.position())
        if self.editable and self._start is not None and end is not None:
            line = GateLine(
                self._start.x(),
                self._start.y(),
                end.x(),
                end.y(),
                self.line.entry_positive if self.line else True,
            )
            if math.hypot(line.x2 - line.x1, line.y2 - line.y1) >= 0.02:
                self.line = line
                self.line_changed.emit(line)
                self.update()
        self._start = None
