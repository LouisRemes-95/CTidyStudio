import sys
from pathlib import Path
from enum import Enum

import numpy as np
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtGui import QImage, QPixmap
from rich.live import Live
from rich.text import Text

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import load_tif_stack


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


class CTidyStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)


        self.top_slice_view = SliceView()
        self.bot_slice_view = SliceView()
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
    def __init__(self):
        super().__init__()

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


    def set_image(self, image: np.ndarray):
        if image.ndim != 2:
            raise ValueError("Expected a 2D array")
        
        if image.dtype != np.uint8:
            raise ValueError("Expected uint8 image")

        image = np.ascontiguousarray(image)
        
        qimage = QImage(
            image.data,
            image.shape[1],
            image.shape[0],
            image.shape[1],
            QImage.Format.Format_Grayscale8,
            ).copy()
        
        pixmap = QPixmap.fromImage(qimage)

        self._pixmap_item.setPixmap(pixmap)

    def showEvent(self, event):
        super().showEvent(event)

        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = 1.0

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
            factor = 1/factor

        factor = max(factor, 1.0 / self._zoom)

        self._zoom *= factor
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
        window = CTidyStudio()
        window.top_slice_view.set_image(scan.data[:,:,1])
        window.bot_slice_view.set_image(scan.data[:,:,100])
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