import sys
from pathlib import Path
from enum import Enum
from typing import Final, Callable
import numpy as np
import math
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import (
    QObject,
    Signal,
    Qt,
    QPoint,
    QPointF,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QGraphicsView,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QPushButton,
    QGraphicsDropShadowEffect,
    QGraphicsLineItem,
    QLineEdit,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QPixmap,
    QPen,
    QFont,
)
from rich.live import Live
from rich.text import Text
from scipy.spatial.transform import Rotation

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import (
    CardinalDirection,
    Orientation,
    Scan,
    Point
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
    view_changed = Signal()
    slice_pos_changed = Signal()

    def __init__(self, scan: Scan) -> None:
        super().__init__()
        self._scan = scan
        self._scan_rotation_in_view_ref = Rotation.identity()
        self._slice_pos = Point(np.array([0, 0, 0]))

    @property
    def scan(self):
        return self._scan

    @property
    def scan_rotation_in_view_ref(self):
        return self._scan_rotation_in_view_ref
    
    @property
    def slice_pos(self):
        return self._slice_pos
    
    def fire_all_signals(self):
        self.view_changed.emit()
        self.slice_pos_changed.emit()

    def on_rotation_request(self, rotation: Rotation) -> None:
        self._scan_rotation_in_view_ref = rotation * self._scan_rotation_in_view_ref
        self.view_changed.emit()
    
    def on_move_slice_pos_request(self, direction: CardinalDirection, value: int):
        self._slice_pos.move(direction, value)

        self.slice_pos_changed.emit()

    def on_set_slice_pos_request(self, direction: CardinalDirection, value: int):
        self._slice_pos.move_to(direction, value)

        self.slice_pos_changed.emit()

class CTidyStudio(QMainWindow):
    def __init__(self, scan: Scan) -> None:
        super().__init__()

        self.app_state = AppState(scan)

        self._build_slice_views()
        self._build_ui()

        self.app_state.fire_all_signals()

    def _build_slice_views(self):

        self.top_slice_view = SliceView(self.app_state, Orientation(CardinalDirection.Z_, CardinalDirection.Y))
        self.bot_slice_view = SliceView(self.app_state, Orientation(CardinalDirection.X, CardinalDirection.Y))

    def _build_ui(self) -> None:
        self.setWindowTitle("CTidyStudio")
        self.resize(1000, 700)

        main_container = QWidget()
        self.setCentralWidget(main_container)
        main_layout = QHBoxLayout(main_container)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        left_layout.addWidget(self.top_slice_view, 1)
        left_layout.addWidget(self.bot_slice_view, 1)

        right_container = QFrame()
        right_container.setObjectName("rightFrame")

        right_container.setStyleSheet("""
        #rightFrame {
            background-color: #2b2b2b;
            border-radius: 15px;
            border: 1px solid #696969;
        }
        """)

        right_layout = QVBoxLayout(right_container)

        binding = IncrementControlBinding(partial(self.app_state.on_move_slice_pos_request, CardinalDirection.X),
                                       partial(self.app_state.on_set_slice_pos_request, CardinalDirection.X),
                                       self.app_state.slice_pos_changed,
                                       lambda: self.app_state.slice_pos.coord[CardinalDirection.X.dir])

        increment_button = self._create_increment_control(right_container, binding)

        right_layout.addWidget(increment_button, 1)

        main_layout.addWidget(left_container, 2)
        main_layout.addWidget(right_container, 1)

    @staticmethod
    def _create_increment_control(parent: QObject, binding: "IncrementControlBinding") -> "IncrementControl":
        control = IncrementControl(parent)

        control.increment_requested.connect(binding.on_increment)
        control.value_submitted.connect(binding.on_submit)
        
        binding.refresh_signal.connect(lambda: control.set_value(binding.read_value()))

        return control

class SliceView(QGraphicsView):
    BAR_WIDTH_RATIO: Final = 0.1
    BAR_HEIGHT_RATIO: Final = 0.015
    BAR_MARGIN_RATIO: Final = 0.05
    BTN_SIZE_RATIO: Final = 0.04
    BTN_MARGIN_RATIO: Final = 0.02
    SLICE_LINE_RATIO: Final = 0.005

    ZOOM_FACTOR: Final = 1.15

    rotation_request = Signal(CardinalDirection)
    

    @property
    def rotation(self):
        return self._view_orientation.rotate(self.app_state.scan_rotation_in_view_ref.inv()).rotation.inv()

    def __init__(self, app_state: AppState, view_orientation: Orientation) -> None:
        super().__init__()

        self.app_state = app_state
        self._view_orientation = view_orientation
        self._view_center = Point(np.array([0, 0, 0])) # In scan coordinates

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

        self._horizontal_slice_line = QGraphicsLineItem(parent = self._pixmap_item)
        self._vertical_slice_line = QGraphicsLineItem(parent = self._pixmap_item)

    def _build_conections(self):
        self.rotation_request.connect(self.app_state.on_rotation_request)

        self.app_state.view_changed.connect(self._update_view)
        self.app_state.view_changed.connect(self._update_slice_lines)
        self.app_state.slice_pos_changed.connect(self._update_slice_lines)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        
        self._update_slice_lines()
        self._fit_view(False)

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

    def _update_view(self):
        rotated_data = self.app_state.scan.rotate_data(self.rotation)
        rotated_slice_pos = self._global_to_view_coord(self.app_state.slice_pos).int_coord

        image = np.flipud(rotated_data[:,:,rotated_slice_pos[2]].T)
        
        if image.dtype != np.uint8:
            raise ValueError("Expected uint8 image")

        image = np.ascontiguousarray(image)
        
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

        self._center_view()
        self._fit_view(True)

    def _update_view_center(self):
        pixmap_center = self._pixmap_item.mapFromScene(self.mapToScene(self.viewport().rect().center()))
        self._view_center = self._view_to_global_coord(self._pixmap_to_view_coord(pixmap_center))

    def _center_view(self):
        view_center_in_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(self._view_center))
        
        self.centerOn(view_center_in_pixmap_coord)

    def _global_to_view_coord(self, point: Point) -> Point:
        return point.rotate_with_scan_center(self.rotation, self.app_state.scan.center)
    
    def _view_to_global_coord(self, point: Point) -> Point:
        return point.rotate_with_scan_center(self.rotation.inv(), self._global_to_view_coord(self.app_state.scan.center))
    
    def _view_to_pixmap_coord(self, point: Point) -> QPointF:
        return QPointF(point.coord[0] + .5, self._pixmap_item.boundingRect().height() - .5 - point.coord[1])
    
    def _pixmap_to_view_coord(self, point: QPointF) -> Point:
        slice_pos_in_view_coord = self._global_to_view_coord(self.app_state.slice_pos)

        return Point(np.array([point.x() - .5, self._pixmap_item.boundingRect().height() - point.y() + .5, slice_pos_in_view_coord.coord[2]]))

    def _fit_view(self, crop_only: bool = False) -> None:
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull():
            return

        fit_scale = min(self.viewport().width() / pixmap.width(), self.viewport().height() / pixmap.height()) / self.transform().m11()

        if not crop_only or (fit_scale > 1):
            self.scale(fit_scale, fit_scale)
        
        self._update_view_center()
        self._update_slice_line_thickness()

    def _update_slice_lines(self):
        view_orientation_in_view_coord = self._view_orientation.rotate(self.app_state._scan_rotation_in_view_ref.inv())

        slice_pos_in_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(self.app_state.slice_pos))
        
        self._horizontal_slice_line.setLine(0, slice_pos_in_pixmap_coord.y(), self._pixmap_item.boundingRect().width(), slice_pos_in_pixmap_coord.y())
        self._horizontal_slice_line.setPen(QPen(view_orientation_in_view_coord.right.associated_color, 1))
        self._horizontal_slice_line.setZValue(10)
        
        self._vertical_slice_line.setLine(slice_pos_in_pixmap_coord.x(), 0, slice_pos_in_pixmap_coord.x(), self._pixmap_item.boundingRect().height())
        self._vertical_slice_line.setPen(QPen(view_orientation_in_view_coord.up.associated_color, 1))
        self._vertical_slice_line.setZValue(10)
        self._update_slice_line_thickness()

    def _update_slice_line_thickness(self):
        min_viewport_dimension = min(self.viewport().height(), self.viewport().width()) / self.transform().m11()
        line_thickness = min_viewport_dimension * self.SLICE_LINE_RATIO

        self._horizontal_slice_line.setPen(QPen(self._horizontal_slice_line.pen().color(), line_thickness))
        
        self._vertical_slice_line.setPen(QPen(self._vertical_slice_line.pen().color(), line_thickness))

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
        view_orientation = self._view_orientation
        direction = view_orientation.forward if clockwise else -view_orientation.forward

        self.rotation_request.emit(direction.rotation_around_direction)
        pass
    
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


@dataclass(slots=True)
class IncrementControlBinding:
    on_increment: Callable[[int], None]
    on_submit: Callable[[int], None]
    refresh_signal: Signal
    read_value: Callable[[], int]


class IncrementControl(QWidget):
    increment_requested = Signal(int)
    value_submitted = Signal(int)

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)

        self._build_dependencies()
        
    class IncrementButton(QPushButton):
        def __init__(self, text: str, increment: int, on_increment_signal: Signal, parent: QObject = None) -> None:
            super().__init__(text, parent)

            self._increment = increment
            self._on_increment_signal = on_increment_signal

            self.setCursor(Qt.PointingHandCursor)
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3a3a3a;
                    color: white;
                    border: 1px solid #666;
                    border-radius: 6px;
                    padding: 6px 10px;
                }
                QPushButton:hover {
                    background-color: #4a6fa5;
                    border: 1px solid #7aa2d6;
                }
                QPushButton:pressed {
                    background-color: #34527a;
                }
            """)

            self.clicked.connect(self._on_clicked)

        def _on_clicked(self):
            self._on_increment_signal.emit(self._increment)

    def _build_dependencies(self) -> None:
        layout = QHBoxLayout(self)
        layout.setSpacing(10)

        self._decrease_100_btn = self.IncrementButton("---", -100, self.increment_requested, parent = self)
        self._decrease_10_btn = self.IncrementButton("--", -10, self.increment_requested, parent = self)
        self._decrease_1_btn = self.IncrementButton("-", -1, self.increment_requested, parent = self)

        self._editable_display = QLineEdit(parent = self)
        fm = self._editable_display.fontMetrics()
        self._editable_display.setMinimumWidth(fm.horizontalAdvance("0000000"))
        self._editable_display.setAlignment(Qt.AlignCenter)
        self._editable_display.returnPressed.connect(self._on_value_submitted)

        self._increase_1_btn = self.IncrementButton("+", 1, self.increment_requested, parent = self)
        self._increase_10_btn = self.IncrementButton("++", 10, self.increment_requested, parent = self)
        self._increase_100_btn = self.IncrementButton("+++", 100, self.increment_requested, parent = self)

        layout.addWidget(self._decrease_100_btn, 1)
        layout.addWidget(self._decrease_10_btn, 1)
        layout.addWidget(self._decrease_1_btn, 1)
        layout.addWidget(self._editable_display, 1)
        layout.addWidget(self._increase_1_btn, 1)
        layout.addWidget(self._increase_10_btn, 1)
        layout.addWidget(self._increase_100_btn, 1)

        self.setStyleSheet("""
            #controlPanel {
                background-color: #2b2b2b;
                border: 1px solid white;
                border-radius: 12px;
            }
            QLineEdit {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #666;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLineEdit:focus {
                border: 1px solid #7aa2d6;
            }
        """)

    def _on_value_submitted(self) -> None:
        text = self._editable_display.text().strip()
        if not text:
            return

        self.value_submitted.emit(int(text))

    def set_value(self, value: int) -> None:
        print("set_value")
        self._editable_display.setText(str(value))

class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


def run_ctidy_studio(input_dir: Path, output_dir: Path, mode: Mode, voxel_size: float) -> int:
    with console.status("[cyan]Loading tif stack..."):
        scan = Scan.from_tif_stack(input_dir, voxel_size)
        
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



# import sys
# from pathlib import Path
# from enum import Enum
# from typing import Final, Callable, Any
# import math
# from functools import partial
# from dataclasses import dataclass
# import copy

# import numpy as np
# from PySide6.QtCore import (
#     Qt,
#     QPoint,
#     Signal,
#     QPointF,
#     QObject,
#     QTimer,
# )
# from PySide6.QtWidgets import (
#     QApplication,
#     QMainWindow,
#     QGraphicsView,
#     QGraphicsScene,
#     QGraphicsPixmapItem,
#     QWidget,
#     QHBoxLayout,
#     QVBoxLayout,
#     QPushButton,
#     QGraphicsDropShadowEffect,
#     QGraphicsLineItem,
#     QGraphicsRectItem,
#     QGraphicsEllipseItem,
#     QFrame,
#     QLineEdit,
#     QLabel,
# )
# from PySide6.QtGui import (
#     QImage,
#     QPixmap,
#     QPen,
#     QFont,
#     QColor,
#     QBrush,
# )
# from rich.live import Live
# from rich.text import Text
# from scipy.spatial.transform import Rotation as R

# from ctidystudio.common import UserError, console
# from ctidystudio.data_handling import (
#     Scan,
#     CardinalDirection,
#     Orientation,
#     DomainOfInterest,
#     rotate_and_translate_point,
#     view_to_pixmap_coord,
#     pixmap_to_view_coord,
#     load_tif_stack,
#     ROTATION_LOOKUP,
#     RotationKey
# )


# SI_PREFIXES = {
#     -12: "p",   # pico
#     -9:  "n",   # nano
#     -6:  "µ",   # micro
#     -3:  "m",   # milli
#      0:  "",    # base
#      3:  "k",   # kilo
#      6:  "M",   # mega
#      9:  "G",   # giga
# }


# def _to_si(x: int, unit: str = "m") -> str:
#     if x == 0:
#         return f"0 {unit}"

#     exp = int(math.floor(math.log10(abs(x))))
#     exp3 = (exp // 3) * 3

#     prefix = SI_PREFIXES.get(exp3, "")
#     value = x / (10 ** exp3)

#     return f"{value:.2f} {prefix}{unit}"


# class AppState(QObject):
#     doi_changed = Signal()
#     slice_changed = Signal()
#     view_changed = Signal()

#     def __init__(self, scan: Scan) -> None:
#         super().__init__()
#         self._scan = scan
#         self._doi = DomainOfInterest(scan.shape)
#         self._slice_pos = np.array([0, 0, 0])
#         self._view_rotation = R.identity()

#     @property
#     def scan(self):
#         return self._scan
    
#     @property
#     def doi(self):
#         return self._doi
    
#     @property
#     def slice_pos(self):
#         return self._slice_pos
    
#     @property
#     def view_center(self):
#         return self._rotation_center
    
#     @property
#     def view_rotation(self):
#         return self._view_rotation

#     def fire_init_signals(self) -> None:
#         self.doi_changed.emit()
#         self.slice_changed.emit()
#         self.view_changed.emit()

#     def on_rotation_request(self, rotation_axis: CardinalDirection) -> None:
#         self._view_rotation = rotation_axis.rotation_around_direction * self._view_rotation
#         self.view_changed.emit()

#     def create_getter(self, attr_name: str) -> Callable[[], Any]:
#         return lambda: getattr(self, attr_name)
    
#     def create_setter(self, attr_path: str, signal: Signal = None) -> Callable[[Any], None]:
#         def setter(value: any) -> None:
#             setattr(self, attr_path, value)

#             if signal is not None:
#                 signal.emit()

#         return setter
    
#     def on_move_doi_origin_request(self, direction: CardinalDirection, increment: int) -> None:
#         self._doi.move_origin(direction, increment)
#         self.doi_changed.emit()

#     def on_set_doi_origin_request(self, direction: CardinalDirection, value: int) -> None:
#         self._doi.set_origin_component(direction, value)
#         self.doi_changed.emit()


# class CTidyStudio(QMainWindow):
#     def __init__(self, scan: Scan) -> None:
#         super().__init__()

#         self.app_state = AppState(scan)

#         self._build_slice_views()
#         self._build_ui()

#         self.app_state.fire_init_signals()
    
#     def _build_slice_views(self):

#         self.top_slice_view = SliceView(self.app_state, Orientation(CardinalDirection.Z_, CardinalDirection.Y))
#         self.bot_slice_view = SliceView(self.app_state, Orientation(CardinalDirection.X, CardinalDirection.Y))

#     def _build_ui(self) -> None:
#         self.setWindowTitle("CTidyStudio")
#         self.resize(1000, 700)

#         main_container = QWidget()
#         self.setCentralWidget(main_container)
#         main_layout = QHBoxLayout(main_container)
#         main_layout.setContentsMargins(10, 10, 10, 10)
#         main_layout.setSpacing(10)

#         left_container = QWidget()
#         left_layout = QVBoxLayout(left_container)
#         left_layout.setContentsMargins(0, 0, 0, 0)
#         left_layout.setSpacing(10)

#         left_layout.addWidget(self.top_slice_view, 1)
#         left_layout.addWidget(self.bot_slice_view, 1)

#         right_container = QFrame()
#         right_container.setObjectName("rightFrame")

#         right_container.setStyleSheet("""
#         #rightFrame {
#             background-color: #2b2b2b;
#             border-radius: 15px;
#             border: 1px solid #696969;
#         }
#         """)

#         right_layout = QVBoxLayout(right_container)

#         increment_button = self._build_right_Widget()

#         right_layout.addWidget(increment_button, 1)

#         main_layout.addWidget(left_container, 2)
#         main_layout.addWidget(right_container, 1)

#     def _build_right_Widget(self) -> QWidget:
#         return self._create_increment_control(self._bind_doi_origin(CardinalDirection.X))

#     def _create_increment_control(self, binding: "IncrementControlBinding") -> "IncrementControl":
#         control = IncrementControl(self)

#         control.increment_requested.connect(binding.on_increment)
#         control.value_submitted.connect(binding.on_submit)
        
#         binding.refresh_signal.connect(lambda: control.set_value(binding.read_value()))

#         return control

#     def _bind_doi_origin(self, direction: CardinalDirection) -> "IncrementControlBinding":
#         return IncrementControlBinding(partial(self.app_state.on_move_doi_origin_request, direction),
#                                        partial(self.app_state.on_set_doi_origin_request, direction),
#                                        self.app_state.doi_changed,
#                                        lambda: self.app_state.doi.origin_coord_in_direction(direction))
 

# class SliceView(QGraphicsView):
#     BAR_WIDTH_RATIO: Final = 0.1
#     BAR_HEIGHT_RATIO: Final = 0.015
#     BAR_MARGIN_RATIO: Final = 0.05
#     BTN_SIZE_RATIO: Final = 0.04
#     BTN_MARGIN_RATIO: Final = 0.02

#     ZOOM_FACTOR: Final = 1.15

#     rotation_request = Signal(CardinalDirection)

#     def __init__(self, app_state: AppState, initial_orientation: Orientation) -> None:
#         super().__init__()

#         self.app_state = app_state
#         self._initial_orientation = initial_orientation
#         self._update_view_orientation()

#         self._view_center = QPointF(0, 0)

#         self._build_view()
#         self._build_dependencies()
#         self._build_conections()

#     def _build_view(self) -> None:
#         self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
#         self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

#         self._panning = False
#         self._pan_start = QPoint()

#         self.setDragMode(QGraphicsView.NoDrag)

#         self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
#         self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

#     def _build_dependencies(self) -> None:
#         self.scene = QGraphicsScene(self)
#         self.setScene(self.scene)

#         self._pixmap_item = QGraphicsPixmapItem()
#         self.scene.addItem(self._pixmap_item)

#         self._rotate_cw_btn = self._create_overlay_button("⟳", lambda: self._on_rotation_btn_clicked(True))
#         self._rotate_ccw_btn = self._create_overlay_button("⟲", lambda: self._on_rotation_btn_clicked(False))

#         self._build_doi_item()

#     def _build_doi_item(self) -> None:
#         self._doi_item = QGraphicsRectItem(parent=self._pixmap_item)
#         self._doi_item.setPen(QPen(Qt.red, 1))
#         self._doi_item.setZValue(10)
    
#     def _build_conections(self):
#         self.rotation_request.connect(self.app_state.on_rotation_request)

#         self.app_state.slice_changed.connect(self._update_scan_view)

#         self.app_state.doi_changed.connect(self._update_doi_view)

#         self.app_state.view_changed.connect(self._update_view_orientation)
#         self.app_state.view_changed.connect(self._update_scan_view)
#         self.app_state.view_changed.connect(self._update_doi_view)

#     def showEvent(self, event) -> None:
#         super().showEvent(event)
        
#         self._fit_view(False)
    
#     def resizeEvent(self, event) -> None:
#         super().resizeEvent(event)

#         old = event.oldSize()
#         new = event.size()

#         if old.width() > 0 and old.height() > 0:
#             ratio = min(
#                 (new.width() / old.width(), new.height() / old.height()),
#                 key=lambda x: abs(x - 1),
#             )
#             self.scale(ratio, ratio)
#         self._fit_view(True)

#         w = self.viewport().width()
#         h = self.viewport().height()

#         size = int(w * self.BTN_SIZE_RATIO)
#         horizontal_margin = int(w * self.BTN_MARGIN_RATIO)
#         vertical_margin = int(h * self.BTN_MARGIN_RATIO)

#         # resize buttons
#         self._rotate_cw_btn.setFixedSize(size, size)
#         self._rotate_ccw_btn.setFixedSize(size, size)

#         # scale font
#         font_size = int(size * 1.2)
#         font = self._rotate_cw_btn.font()
#         font.setPixelSize(font_size)

#         self._rotate_cw_btn.setFont(font)
#         self._rotate_ccw_btn.setFont(font)

#         # position
#         self._rotate_cw_btn.move(horizontal_margin + size + horizontal_margin, vertical_margin)
#         self._rotate_ccw_btn.move(horizontal_margin, vertical_margin)
    
#     def _fit_view(self, crop_only: bool = False) -> None:
#         pixmap = self._pixmap_item.pixmap()
#         if pixmap.isNull():
#             return

#         fit_scale = min(self.viewport().width() / pixmap.width(), self.viewport().height() / pixmap.height()) / self.transform().m11()

#         if not crop_only or (fit_scale > 1):
#             self.scale(fit_scale, fit_scale)
        
#         self._update_view_center()

#     def drawForeground(self, painter, rect) -> None:
#         super().drawForeground(painter, rect)

#         painter.save()
#         painter.resetTransform()  # keep overlay fixed to the viewport

#         # scale line
#         w = self.viewport().width()
#         h = self.viewport().height()

#         bar_width = int(w * self.BAR_WIDTH_RATIO)
#         bar_height = int(h * self.BAR_HEIGHT_RATIO)

#         horizontal_margin = int(w * self.BAR_MARGIN_RATIO)
#         vertical_margin = int(h * self.BAR_MARGIN_RATIO)

#         x = w - horizontal_margin - bar_width
#         y = h - vertical_margin - bar_height

#         painter.fillRect(x, y, bar_width, bar_height, Qt.GlobalColor.white)

#         pen = QPen(Qt.GlobalColor.black, 1)
#         painter.setPen(pen)
#         painter.drawRect(x, y, bar_width, bar_height)

#         # scale text
#         real_size = self.app_state.scan.voxel_size / 1000 * bar_width / self.transform().m11()
#         text = _to_si(real_size)

#         font = QFont()
#         font.setPointSizeF(bar_width / 4)
#         painter.setFont(font)

#         fm = painter.fontMetrics()
#         text_width = fm.horizontalAdvance(text)

#         text_x = x + (bar_width - text_width) // 2
#         text_y = y - bar_height * 2

#         # black outline
#         painter.setPen(Qt.GlobalColor.black)
#         painter.drawText(text_x - 1, text_y, text)
#         painter.drawText(text_x + 1, text_y, text)
#         painter.drawText(text_x, text_y - 1, text)
#         painter.drawText(text_x, text_y + 1, text)

#         painter.setPen(Qt.GlobalColor.white)
#         painter.drawText(text_x, text_y, text)

#         painter.restore()

#     # def _draw_line(self) -> None:
#     #     pixmap_item = self._pixmap_item
#     #     self.line = QGraphicsLineItem(0, 0, 0, pixmap_item.boundingRect().height(), pixmap_item)
#     #     self.line.setPen(QPen(Qt.red, 2))
#     #     self.line.setZValue(10)

#     def _update_view_orientation(self) -> None:
#         self._view_orientation = self._initial_orientation.copy()
#         self._view_orientation.rotate(self.app_state.view_rotation)

#     def _update_scan_view(self):
#         forward_dir = self._view_orientation.forward.dir
#         up_direction = self._view_orientation.up
#         right_direction = self._view_orientation.right

#         image = np.take(self.app_state.scan.data, self.app_state.slice_pos[forward_dir], axis = forward_dir)
#         if up_direction.dir > right_direction.dir:
#             image = image.T

#         if up_direction.vec[up_direction.dir] < 0:
#             image = np.flip(image, axis = 1)

#         if right_direction.vec[right_direction.dir] > 0:
#             image = np.flip(image, axis = 0)
        
#         if image.dtype != np.uint8:
#             raise ValueError("Expected uint8 image")

#         image = np.ascontiguousarray(image)
        
#         qimage = QImage(
#             image,
#             image.shape[1],
#             image.shape[0],
#             image.shape[1],
#             QImage.Format.Format_Grayscale8,
#             ).copy()
        
#         pixmap = QPixmap.fromImage(qimage)

#         self._pixmap_item.setPixmap(pixmap)

#         self.scene.setSceneRect(self._pixmap_item.boundingRect())

#         self._fit_view(True)
#         self._center_view()

#     def _update_view_center(self):
#         self._view_center = self._pixmap_item.mapFromScene(self.mapToScene(self.viewport().rect().center()))
    
#     def _center_view(self) -> None:
#         self.centerOn(self._view_center)
    
#     def _update_doi_view(self):
#         self._doi_item.setRect(self.app_state.doi.view_box(self._view_orientation, self._pixmap_item.boundingRect().height()))
#         self._doi_item.update()
#         self.viewport().update()

#     def mousePressEvent(self, event) -> None:
#         if event.button() == Qt.RightButton:
#             self._panning = True
#             self._pan_start = event.pos()
#             event.accept()
#             return

#         super().mousePressEvent(event)

#     def mouseMoveEvent(self, event) -> None:
#         if self._panning:
#             delta = event.pos() - self._pan_start
#             self._pan_start = event.pos()

#             self.horizontalScrollBar().setValue(
#                 self.horizontalScrollBar().value() - delta.x()
#             )
#             self.verticalScrollBar().setValue(
#                 self.verticalScrollBar().value() - delta.y()
#             )

#             event.accept()
#             self.viewport().update()
#             self._update_view_center()
#             return

#         super().mouseMoveEvent(event)

#     def mouseReleaseEvent(self, event) -> None:
#         if event.button() == Qt.RightButton:
#             self._panning = False
#             event.accept()
#             return

#         super().mouseReleaseEvent(event)

#     def wheelEvent(self, event) -> None:
#         factor = self.ZOOM_FACTOR
#         if event.angleDelta().y() < 0:
#             factor = 1 / factor

#         self.scale(factor, factor)

#         self._fit_view(True)
        
#     def _create_overlay_button(self, text: str, func: Callable) -> QPushButton:
#         btn = QPushButton(text, self)
#         btn.setFixedSize(36, 36)
#         btn.setCursor(Qt.PointingHandCursor)
#         btn.setFocusPolicy(Qt.NoFocus)

#         # shadow (outline effect)
#         shadow = QGraphicsDropShadowEffect(btn)
#         shadow.setBlurRadius(0)
#         shadow.setOffset(0, 0)
#         shadow.setColor(QColor(0, 0, 0))
#         btn.setGraphicsEffect(shadow)

#         # style
#         btn.setStyleSheet("""
#             QPushButton {
#                 background: transparent;
#                 color: white;
#                 border: none;
#                 border-radius: 0px;
#                 font-weight: bold;
#                 padding: 0px;
#                 margin: 0px;
#             }
#             QPushButton:hover {
#                 color: rgb(51, 153, 255);
#             }
#             QPushButton:pressed {
#                 color: rgba(51, 153, 255, 120);
#             }
#         """)

#         btn.clicked.connect(func)

#         return btn

#     def _on_rotation_btn_clicked(self, clockwise: bool) -> None:
#         view_orientation = self._view_orientation
#         direction = view_orientation.forward if clockwise else -view_orientation.forward

#         slice_index = int(np.dot(self.app_state.slice_pos, view_orientation.forward.vec))
#         world_center = pixmap_to_view_coord(self._view_center, view_orientation, self._pixmap_item.boundingRect().height(), slice_index)

#         self.rotation_request.emit(direction)

#         self._view_center = view_to_pixmap_coord(world_center, self._view_orientation, self._pixmap_item.boundingRect().height())

#         self._center_view()


# @dataclass(slots=True)
# class IncrementControlBinding:
#     on_increment: Callable[[int], None]
#     on_submit: Callable[[int], None]
#     refresh_signal: Signal
#     read_value: Callable[[], int]


# class IncrementControl(QWidget):
#     increment_requested = Signal(int)
#     value_submitted = Signal(int)

#     def __init__(self, parent: QObject = None) -> None:
#         super().__init__(parent)

#         self._build_dependencies()
        
#     class IncrementButton(QPushButton):
#         def __init__(self, text: str, increment: int, on_increment_signal: Signal, parent: QObject = None) -> None:
#             super().__init__(text, parent)

#             self._increment = increment
#             self._on_increment_signal = on_increment_signal

#             self.setCursor(Qt.PointingHandCursor)
#             self.setStyleSheet("""
#                 QPushButton {
#                     background-color: #3a3a3a;
#                     color: white;
#                     border: 1px solid #666;
#                     border-radius: 6px;
#                     padding: 6px 10px;
#                 }
#                 QPushButton:hover {
#                     background-color: #4a6fa5;
#                     border: 1px solid #7aa2d6;
#                 }
#                 QPushButton:pressed {
#                     background-color: #34527a;
#                 }
#             """)

#             self.clicked.connect(self._on_clicked)

#         def _on_clicked(self):
#             self._on_increment_signal.emit(self._increment)

#     def _build_dependencies(self) -> None:
#         layout = QHBoxLayout(self)
#         layout.setSpacing(10)

#         self._decrease_100_btn = self.IncrementButton("-100", -100, self.increment_requested, parent=self)
#         self._decrease_10_btn = self.IncrementButton("-10", -10, self.increment_requested, parent=self)
#         self._decrease_1_btn = self.IncrementButton("-1", -1, self.increment_requested, parent=self)

#         self._editable_display = QLineEdit()
#         self._editable_display.setPlaceholderText("value")
#         self._editable_display.returnPressed.connect(self._on_value_submitted)

#         self._increase_1_btn = self.IncrementButton("+1", 1, self.increment_requested, parent=self)
#         self._increase_10_btn = self.IncrementButton("+10", 10, self.increment_requested, parent=self)
#         self._increase_100_btn = self.IncrementButton("+100", 100, self.increment_requested, parent=self)

#         layout.addWidget(self._decrease_100_btn, 1)
#         layout.addWidget(self._decrease_10_btn, 1)
#         layout.addWidget(self._decrease_1_btn, 1)
#         layout.addWidget(self._editable_display, 1)
#         layout.addWidget(self._increase_1_btn, 1)
#         layout.addWidget(self._increase_10_btn, 1)
#         layout.addWidget(self._increase_100_btn, 1)

#         self.setStyleSheet("""
#             #controlPanel {
#                 background-color: #2b2b2b;
#                 border: 1px solid white;
#                 border-radius: 12px;
#             }
#             QLineEdit {
#                 background-color: #3a3a3a;
#                 color: white;
#                 border: 1px solid #666;
#                 border-radius: 6px;
#                 padding: 6px 10px;
#             }
#             QLineEdit:focus {
#                 border: 1px solid #7aa2d6;
#             }
#         """)

#     def _on_value_submitted(self) -> None:
#         text = self._editable_display.text().strip()
#         if not text:
#             return

#         self.value_submitted.emit(int(text))

#     def set_value(self, value: int) -> None:
#         self._editable_display.setText(str(value))




# def run_ctidy_studio(input_dir: Path, output_dir: Path, mode: Mode, voxel_size: float) -> int:
#     with console.status("[cyan]Loading tif stack..."):
#         scan = load_tif_stack(input_dir, voxel_size)
#         scan.quantization_to_uint8()
#     console.print("[green]✔ Tif stack loaded[/green]")

#     match mode:
#         case Mode.RESET:
#             pass
#         case Mode.RESUME:
#             pass
#         case Mode.SILENT:
#             pass
#         case _:
#             raise ValueError(f"Unknown mode: {mode}")
        
#     app = QApplication.instance() or QApplication(sys.argv)
        
#     with Live(Text.from_markup("[cyan]Opening CTidy Studio...[/cyan]"), console=console, transient=True):
#         scan.data[:10,:40,:100] = 0
#         window = CTidyStudio(scan)
#         window.show()
#         exit_code = app.exec()

#     if exit_code == 0:
#         console.print("[green]✔ Scan handling complete[/green]")

#     return exit_code

# # TO DO:
#         # try:
#         #     rel = output_dir.relative_to(Path.cwd())
#         # except ValueError:
#         #     rel = output_dir

#         # console.print(f"💾 Wrote to: {rel}")