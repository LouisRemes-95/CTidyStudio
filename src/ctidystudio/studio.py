import sys
from pathlib import Path
from enum import Enum
from typing import Final, Callable
import math

import numpy as np
from PySide6.QtCore import (
    Qt,
    QPoint,
    Signal,
    QPointF,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QGraphicsDropShadowEffect,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPen,
    QFont,
    QColor,
)
from rich.live import Live
from rich.text import Text

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import load_tif_stack, Scan


SI_PREFIXES = {
    -12: "p",   # pico
    -9:  "n",   # nano
    -6:  "µ",   # micro
    -3:  "m",   # milli
     0:  "",    # base
     3:  "k",   # kilo
     6:  "M",   # mega
     9:  "G",   # giga
}


class DirectionPair(tuple, Enum):
    YX = (1, 0)
    YZ = (1, 2)


def _to_si(x: int, unit: str = "m") -> str:
    if x == 0:
        return f"0 {unit}"

    exp = int(math.floor(math.log10(abs(x))))
    exp3 = (exp // 3) * 3

    prefix = SI_PREFIXES.get(exp3, "")
    value = x / (10 ** exp3)

    return f"{value:.2f} {prefix}{unit}"


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


class CTidyStudio(QMainWindow):
    def __init__(self, scan: Scan) -> None:
        super().__init__()

        self.scan = scan
        self.slice_position = (0, 0, 0)
        self._build_ui()
        self._update_ui_data()

    def _build_ui(self) -> None:
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)

        self.top_slice_view = SliceView(self.scan.voxel_size, DirectionPair.YX)
        self.bot_slice_view = SliceView(self.scan.voxel_size, DirectionPair.YZ)

        self.top_slice_view.rotate_request.connect(self._on_rotate_request)
        self.bot_slice_view.rotate_request.connect(self._on_rotate_request)

        right_panel = QWidget()

        main_container = QWidget()
        self.setCentralWidget(main_container)
        main_layout = QHBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)

        left_layout.addWidget(self.top_slice_view, 1)
        left_layout.addWidget(self.bot_slice_view, 1)

        main_layout.addWidget(left_container, 2)
        main_layout.addWidget(right_panel, 1)

    def _update_ui_data(self) -> None:
        self.top_slice_view.set_image(self.scan.data[:, :, self.slice_position[2]], False)
        self.bot_slice_view.set_image(self.scan.data[self.slice_position[0], :, :], False)

    def _on_rotate_request(self, rotation_axis: tuple[int, int], rotation_point: QPointF) -> None:
        self.scan.rot90(rotation_axis)
        self._update_ui_data()
        for view in (self.top_slice_view, self.bot_slice_view):
            if view._direction_pair.value in (rotation_axis, rotation_axis[::-1]):
                view.centerOn(rotation_point)
    

class SliceView(QGraphicsView):
    BAR_WIDTH_RATIO: Final = 0.1
    BAR_HEIGHT_RATIO: Final = 0.015
    BAR_MARGIN_RATIO: Final = 0.05
    BTN_SIZE_RATIO: Final = 0.04
    BTN_MARGIN_RATIO: Final = 0.02

    ZOOM_FACTOR: Final = 1.15

    rotate_request = Signal(tuple, QPointF)

    def __init__(self, voxel_size: float, direction_pair: DirectionPair) -> None:
        super().__init__()

        self.image: np.ndarray | None = None
        self._voxel_size = voxel_size
        self._direction_pair = direction_pair

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self._pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self._pixmap_item)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setDragMode(QGraphicsView.NoDrag)

        self._panning = False
        self._pan_start = QPoint()

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self._rotate_cw_btn = self._create_overlay_button("⟳", lambda: self._emit_rotation_request(True))
        self._rotate_ccw_btn = self._create_overlay_button("⟲", lambda: self._emit_rotation_request(False))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        
        self.fit_view()
    
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

        old = event.oldSize()
        new = event.size()

        if old.width() > 0 and old.height() > 0:
            ratio = min(
                (new.width() / old.width(), new.height() / old.height()),
                key=lambda x: abs(x - 1),
            )
            self.scale(ratio, ratio)
        self.fit_view(True)

        w = self.viewport().width()
        h = self.viewport().height()

        size = int(w * self.BTN_SIZE_RATIO)
        horizontal_margin = int(w * self.BTN_MARGIN_RATIO)
        vertical_margin = int(h * self.BTN_MARGIN_RATIO)

        # resize buttons
        self._rotate_cw_btn.setFixedSize(size, size)
        self._rotate_ccw_btn.setFixedSize(size, size)

        # scale font
        font_size = int(size * 1.2)
        font = self._rotate_cw_btn.font()
        font.setPixelSize(font_size)

        self._rotate_cw_btn.setFont(font)
        self._rotate_ccw_btn.setFont(font)

        # position
        self._rotate_cw_btn.move(horizontal_margin + size + horizontal_margin, vertical_margin)
        self._rotate_ccw_btn.move(horizontal_margin, vertical_margin)

    def set_image(self, image: np.ndarray, fit: bool = False) -> None:
        if image.ndim != 2:
            raise ValueError("Expected a 2D array")
        
        if image.dtype != np.uint8:
            raise ValueError("Expected uint8 image")
        
        self.image = image

        if self._direction_pair == DirectionPair.YX:
            image = image.T

        image = np.ascontiguousarray(np.flipud(image))
        
        qimage = QImage(
            image,
            image.shape[1],
            image.shape[0],
            image.shape[1],
            QImage.Format.Format_Grayscale8,
            ).copy()
        
        pixmap = QPixmap.fromImage(qimage)

        self._pixmap_item.setPixmap(pixmap)

        self.scene.setSceneRect(self._pixmap_item.boundingRect())

        self.fit_view(not fit)
    
    def fit_view(self, crop_only: bool = False) -> None:
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return

        fit_scale = min(self.viewport().width() / pixmap.width(), self.viewport().height() / pixmap.height()) / self.transform().m11()

        if not crop_only or (fit_scale > 1):
            self.scale(fit_scale, fit_scale)

    def drawForeground(self, painter, rect) -> None:
        super().drawForeground(painter, rect)

        painter.save()
        painter.resetTransform()  # keep overlay fixed to the viewport

        # scale line
        w = self.viewport().width()
        h = self.viewport().height()

        bar_width = int(w * self.BAR_WIDTH_RATIO)
        bar_height = int(h * self.BAR_HEIGHT_RATIO)

        horizontal_margin = int(w * self.BAR_MARGIN_RATIO)
        vertical_margin = int(h * self.BAR_MARGIN_RATIO)

        x = w - horizontal_margin - bar_width
        y = h - vertical_margin - bar_height

        painter.fillRect(x, y, bar_width, bar_height, Qt.GlobalColor.white)

        pen = QPen(Qt.GlobalColor.black, 1)
        painter.setPen(pen)
        painter.drawRect(x, y, bar_width, bar_height)

        # scale text
        real_size = self._voxel_size / 1000 * bar_width / self.transform().m11()
        text = _to_si(real_size)

        font = QFont()
        font.setPointSizeF(bar_width / 4)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text)

        text_x = x + (bar_width - text_width) // 2
        text_y = y - bar_height * 2

        # black outline
        painter.setPen(Qt.GlobalColor.black)
        painter.drawText(text_x - 1, text_y, text)
        painter.drawText(text_x + 1, text_y, text)
        painter.drawText(text_x, text_y - 1, text)
        painter.drawText(text_x, text_y + 1, text)

        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(text_x, text_y, text)

        painter.restore()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self._panning = True
            self._pan_start = event.pos()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()

            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )

            event.accept()
            self.viewport().update()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.RightButton:
            self._panning = False
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        factor = self.ZOOM_FACTOR
        if event.angleDelta().y() < 0:
            factor = 1 / factor

        self.scale(factor, factor)

        self.fit_view(True)
        
    def _create_overlay_button(self, text: str, func: Callable) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)

        # shadow (outline effect)
        shadow = QGraphicsDropShadowEffect(btn)
        shadow.setBlurRadius(0)
        shadow.setOffset(0, 0)
        shadow.setColor(QColor(0, 0, 0))
        btn.setGraphicsEffect(shadow)

        # style
        btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: white;
                border: none;
                border-radius: 0px;
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            }
            QPushButton:hover {
                color: rgb(51, 153, 255);
            }
            QPushButton:pressed {
                color: rgba(51, 153, 255, 120);
            }
        """)

        btn.clicked.connect(func)

        return btn

    def _emit_rotation_request(self, clockwise: bool) -> None:
        view_center_pixmap = self._pixmap_item.mapFromScene(self.mapToScene(self.viewport().rect().center()))
        rotated_view_center = _rotate_pixmap_point_90(view_center_pixmap, self._pixmap_item.pixmap().width(), self._pixmap_item.pixmap().height(), clockwise)

        direction = self._direction_pair.value[::-1] if not clockwise else self._direction_pair.value

        self.rotate_request.emit(direction, rotated_view_center)


def _rotate_pixmap_point_90(point: QPointF, width: int, height: int, clockwise: bool) -> QPointF:
    x = point.x()
    y = point.y()

    if clockwise:
        return QPointF(height - 1 - y, x)
    return QPointF(y, width - 1 - x)


def run_ctidy_studio(input_dir: Path, output_dir: Path, mode: Mode, voxel_size: float) -> int:
    with console.status("[cyan]Loading tif stack..."):
        scan = load_tif_stack(input_dir, voxel_size)
        scan.quantization_to_uint8()
    console.print("[green]✔ Tif stack loaded[/green]")

    match mode:
        case Mode.RESET:
            pass
        case Mode.RESUME:
            pass
        case Mode.SILENT:
            pass
        case _:
            raise ValueError(f"Unknown mode: {mode}")
        
    app = QApplication.instance() or QApplication(sys.argv)
        
    with Live(Text.from_markup("[cyan]Opening CTidy Studio...[/cyan]"), console=console, transient=True):
        scan.data[:10,:40,:100] = 0
        window = CTidyStudio(scan)
        window.show()
        exit_code = app.exec()

    if exit_code == 0:
        console.print("[green]✔ Scan handling complete[/green]")

    return exit_code

# TO DO:
        # try:
        #     rel = output_dir.relative_to(Path.cwd())
        # except ValueError:
        #     rel = output_dir

        # console.print(f"💾 Wrote to: {rel}")