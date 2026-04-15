import sys
from pathlib import Path
from enum import Enum
import math

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtWidgets import QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QWidget, QHBoxLayout, QVBoxLayout, QPushButton
from PySide6.QtGui import QImage, QPixmap, QPen, QPainter, QFont
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

class Direction_pair(str, Enum):
    XY = "XY"
    YZ = "YZ"

def _to_SI(x, unit="m"):
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
    def __init__(self, scan: Scan):
        super().__init__()

        self.scan = scan
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)

        self.top_slice_view = SliceView(self.scan.voxel_size, Direction_pair.XY)
        self.bot_slice_view = SliceView(self.scan.voxel_size, Direction_pair.YZ)
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


class SliceView(QGraphicsView):
    def __init__(self, voxel_size: int, direction_pair: Direction_pair):
        super().__init__()

        self._voxel_size = voxel_size
        self._direction_pair = direction_pair

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self._pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self._pixmap_item)
        self.scene.setSceneRect(self._pixmap_item.boundingRect())

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setDragMode(QGraphicsView.NoDrag)

        self._panning = False
        self._pan_start = QPoint()

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self._rotate_btn = QPushButton("⟳", self.viewport())

    def showEvent(self, event):
        super().showEvent(event)
        
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)

    def set_image(self, image: np.ndarray, fit : bool =False):
        if image.ndim != 2:
            raise ValueError("Expected a 2D array")
        
        if image.dtype != np.uint8:
            raise ValueError("Expected uint8 image")

        if self._direction_pair == Direction_pair.XY:
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

        if fit:
            self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def fit_image(self):
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = 1.0

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)

        painter.save()
        painter.resetTransform()  # keep overlay fixed to the viewport

        # scale line
        w = self.viewport().width()
        h = self.viewport().height()

        bar_width = int(w * 0.1)
        bar_height = int(h * 0.015)

        margin = int(w * 0.05)

        x = w - margin - bar_width
        y = h - margin - bar_height

        painter.fillRect(x, y, bar_width, bar_height, Qt.GlobalColor.white)

        pen = QPen(Qt.GlobalColor.black, 1)
        painter.setPen(pen)
        painter.drawRect(x, y, bar_width, bar_height)

        # scale text
        real_size = self._voxel_size / 1000 * bar_width / self.transform().m11()
        text = _to_SI(real_size)

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

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._panning = True
            self._pan_start = event.pos()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
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

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self._panning = False
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1 / factor

        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return

        fit_scale = min(self.viewport().width() / pixmap.width(), self.viewport().height() / pixmap.height()) / self.transform().m11()
        fit_scale = min(fit_scale, 1)

        factor = max(factor, fit_scale)

        self.scale(factor, factor)


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
        window = CTidyStudio(scan)
        scan.data[:10,:40,:100] = 0
        window.top_slice_view.set_image(scan.data[:,:,0], True)
        window.bot_slice_view.set_image(scan.data[0,:,:], True)
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