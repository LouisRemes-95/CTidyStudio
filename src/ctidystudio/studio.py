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
    QObject,
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
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsEllipseItem,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPen,
    QFont,
    QColor,
    QBrush,
)
from rich.live import Live
from rich.text import Text

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import (
    Scan,
    CardinalDirection,
    Orientation,
    DomainOfInterest,
    rotate_and_translate_point,
    view_to_pixmap_coord,
    pixmap_to_view_coord,
    load_tif_stack,
)


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


def _to_si(x: int, unit: str = "m") -> str:
    if x == 0:
        return f"0 {unit}"

    exp = int(math.floor(math.log10(abs(x))))
    exp3 = (exp // 3) * 3

    prefix = SI_PREFIXES.get(exp3, "")
    value = x / (10 ** exp3)

    return f"{value:.2f} {prefix}{unit}"


class AppState(QObject):
    scan_changed = Signal()
    doi_changed = Signal()
    slice_changed = Signal()

    def __init__(self, scan: Scan) -> None:
        super().__init__()
        self._scan = scan
        self._doi = DomainOfInterest(scan.shape)
        self._slice_pos = np.array([0, 0, 0])

    @property
    def scan(self):
        return self._scan
    
    @property
    def doi(self):
        return self._doi
    
    @property
    def slice_pos(self):
        return self._slice_pos
    
    @property
    def view_center(self):
        return self._rotation_center

    def on_rotation_request(self, rotation_axis: CardinalDirection) -> None:
        self._apply_rotation(rotation_axis)
        self.scan_changed.emit()
        self.doi_changed.emit()

    def _apply_rotation(self, rotation_axis: CardinalDirection) -> None:
        previous_center = self._scan.center
        self._scan.rot90(rotation_axis)

        self._doi.rotate_and_translate(rotation_axis, previous_center, self._scan.center)


class CTidyStudio(QMainWindow):
    def __init__(self, scan: Scan) -> None:
        super().__init__()

        self.app_state = AppState(scan)

        self._build_slice_views()
        self._build_ui()
    
    def _build_slice_views(self):

        self.top_slice_view = SliceView(self.app_state, ViewOrientation.FRONT)
        self.bot_slice_view = SliceView(self.app_state, ViewOrientation.SIDE)

    def _build_ui(self) -> None:
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)


        main_container = QWidget()
        self.setCentralWidget(main_container)
        main_layout = QHBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)

        left_layout.addWidget(self.top_slice_view, 1)
        left_layout.addWidget(self.bot_slice_view, 1)

        right_container = QWidget()

        main_layout.addWidget(left_container, 2)
        main_layout.addWidget(right_container, 1)


class ViewOrientation(Enum):
    FRONT = Orientation(CardinalDirection.Z_, CardinalDirection.Y)
    SIDE  = Orientation(CardinalDirection.X,  CardinalDirection.Y)

    @property
    def forward(self):
        return self.value.forward

    @property
    def up(self):
        return self.value.up
 

class SliceView(QGraphicsView):
    BAR_WIDTH_RATIO: Final = 0.1
    BAR_HEIGHT_RATIO: Final = 0.015
    BAR_MARGIN_RATIO: Final = 0.05
    BTN_SIZE_RATIO: Final = 0.04
    BTN_MARGIN_RATIO: Final = 0.02

    ZOOM_FACTOR: Final = 1.15

    rotation_request = Signal(CardinalDirection)

    def __init__(self, app_state: AppState, view_orientation: ViewOrientation) -> None:
        super().__init__()

        self.app_state = app_state
        self._view_orientation = view_orientation

        self._view_center = QPointF(0, 0)

        self._build_view()
        self._build_dependencies()
        self._build_conections()

    def _build_view(self) -> None:
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._panning = False
        self._pan_start = QPoint()

        self.setDragMode(QGraphicsView.NoDrag)

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

    def _build_dependencies(self) -> None:
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self._pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self._pixmap_item)

        self._rotate_cw_btn = self._create_overlay_button("⟳", lambda: self._on_rotation_btn_clicked(True))
        self._rotate_ccw_btn = self._create_overlay_button("⟲", lambda: self._on_rotation_btn_clicked(False))

        self._build_doi_item()

    def _build_doi_item(self) -> None:
        self._doi_item = QGraphicsRectItem(parent=self._pixmap_item)
        self._doi_item.setPen(QPen(Qt.red, 2))
        self._doi_item.setZValue(10)
    
    def _build_conections(self):
        self.rotation_request.connect(self.app_state.on_rotation_request)
        self.app_state.scan_changed.connect(self._update_scan_view)
        self.app_state.doi_changed.connect(self._update_doi_view)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        
        self._update_scan_view()
        self._update_doi_view()
        self._fit_view()
    
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
        self._fit_view(True)

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
    
    def _fit_view(self, crop_only: bool = False) -> None:
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return

        fit_scale = min(self.viewport().width() / pixmap.width(), self.viewport().height() / pixmap.height()) / self.transform().m11()

        if not crop_only or (fit_scale > 1):
            self.scale(fit_scale, fit_scale)
        
        self._update_view_center()

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
        real_size = self.app_state.scan.voxel_size / 1000 * bar_width / self.transform().m11()
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

    # def _draw_line(self) -> None:
    #     pixmap_item = self._pixmap_item
    #     self.line = QGraphicsLineItem(0, 0, 0, pixmap_item.boundingRect().height(), pixmap_item)
    #     self.line.setPen(QPen(Qt.red, 2))
    #     self.line.setZValue(10)

    def _update_scan_view(self):
        direction = self._view_orientation.forward.vec

        if np.count_nonzero(direction) != 1:
            raise ValueError(f"slice_pos must have exactly one non-zero element, got {direction}")

        dim = np.flatnonzero(direction).item()
        image = self.app_state.scan.slice(dim, self.app_state._slice_pos[dim])

        if image.ndim != 2:
            raise ValueError("Expected a 2D array")
        
        if image.dtype != np.uint8:
            raise ValueError("Expected uint8 image")
        
        if self._view_orientation == ViewOrientation.FRONT:
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

        self._fit_view(True)
        self._center_view()

    def _update_view_center(self):
        self._view_center = self._pixmap_item.mapFromScene(self.mapToScene(self.viewport().rect().center()))
    
    def _center_view(self) -> None:
        self.centerOn(self._view_center)
    
    def _update_doi_view(self):
        self._doi_item.setRect(self.app_state.doi.view_box(self._view_orientation.value, self._pixmap_item.boundingRect().height()))

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
            self._update_view_center()
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

        self._fit_view(True)
        
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

    def _on_rotation_btn_clicked(self, clockwise: bool) -> None:
        view_orientation = self._view_orientation.value
        direction = view_orientation.forward if clockwise else -view_orientation.forward

        slice_index = np.dot(self.app_state.slice_pos, view_orientation.forward.vec)
        view_center_coord = pixmap_to_view_coord(self._view_center, view_orientation, self._pixmap_item.boundingRect().height(), slice_index)
        previous_scan_center = self.app_state.scan.center

        self.rotation_request.emit(direction)

        rotated_view_center_coord = rotate_and_translate_point(view_center_coord, direction, previous_scan_center, self.app_state.scan.center)
        self._view_center = view_to_pixmap_coord(rotated_view_center_coord, view_orientation, self._pixmap_item.boundingRect().height())

        self._center_view()


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


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