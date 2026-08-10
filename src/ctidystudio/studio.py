import sys
from pathlib import Path
from enum import Enum
from typing import Final, Callable, Literal, Any
import numpy as np
import math
from dataclasses import dataclass
from functools import partial

import json
from PySide6.QtCore import (
    QObject,
    Signal,
    Qt,
    QPoint,
    QPointF,
    QRectF,
    QLineF,
    QTimer,
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
    QSizePolicy,
    QLabel,
    QScrollArea,
    QGraphicsRectItem,
    QLayout,
    QGraphicsEllipseItem,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QPixmap,
    QPen,
    QFont,
    QPolygonF,
    QBrush,
)
from rich.live import Live
from rich.text import Text
from scipy.spatial.transform import Rotation

from ctidystudio.common import UserError, console
from ctidystudio.data_handling import (
    CardinalDirection,
    Orientation,
    Scan,
    Point,
    IntPoint,
    Domain,
    SamplingDomain,
    SamplingType,
    SnappedRotation,
)


SD_COLOR = QColor("red")
GRID_COLOR = QColor("#18FBFF")


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
    sd_changed = Signal()

    def __init__(self, scan: Scan) -> None:
        super().__init__()
        self._scan = scan
        self._applied_scan_rotation_in_view_ref = SnappedRotation.identity()
        self._current_scan_rotation_in_view_ref = SnappedRotation.identity()
        self._slice_pos = IntPoint(np.array([0, 0, 0]))
        self._slice_pos_show_dir = [False, False, False]
        self._sd = SamplingDomain(IntPoint(np.array([0, 0, 0])), IntPoint(np.array(scan.shape) - 1))
        self._sd_show = False
        self._grid_show = False

    @property
    def scan(self):
        return self._scan

    @property
    def applied_scan_rotation_in_view_ref(self):
        return self._applied_scan_rotation_in_view_ref
    
    @property
    def current_scan_rotation_in_view_ref(self):
        return self._current_scan_rotation_in_view_ref
    
    @property
    def slice_pos(self):
        return self._slice_pos
    
    @property
    def slice_pos_show_dir(self):
        return self._slice_pos_show_dir
    
    @property
    def sd(self):
        return self._sd
    
    @property
    def sd_show(self):
        return self._sd_show
    
    @property
    def grid_show(self):
        return self._grid_show

    def _to_dict(self) -> dict[str, Any]:
        return {
            "applied_scan_rotation_in_view_ref": self.applied_scan_rotation_in_view_ref.key,
            "current_scan_rotation_in_view_ref": self.current_scan_rotation_in_view_ref.key,
            "slice_pos": self.slice_pos.coord.tolist(),
            "slice_pos_show_dir": self.slice_pos_show_dir.copy(),
            "sd": self.sd.to_dict(),
            "sd_show": self._sd_show,
            "grid_show": self._grid_show,
        }

    def save(self, dir: Path) -> None:
        path = dir / "app_state.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(self._to_dict(), file, indent=4)

    def load(self, app_state_path: Path) -> None:
        with app_state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if "applied_scan_rotation_in_view_ref" in data:
            self._current_scan_rotation_in_view_ref = SnappedRotation(tuple(tuple(row) for row in data['applied_scan_rotation_in_view_ref']))
            self.on_apply_rotation_request()

        if "current_scan_rotation_in_view_ref" in data:
            self._current_scan_rotation_in_view_ref = SnappedRotation(tuple(tuple(row) for row in data['current_scan_rotation_in_view_ref']))

        if "slice_pos" in data:
            self._slice_pos = IntPoint(np.array(data['slice_pos']))

        if "slice_pos_show_dir" in data:
            self._slice_pos_show_dir = data['slice_pos_show_dir']

        if "sd" in data:
            sd = SamplingDomain.from_dict(data["sd"])
            if sd is not None:
                self._sd = sd

        if "sd_show" in data:
            self._sd_show = data['sd_show']

        if "grid_show" in data:
            self._grid_show = data['grid_show']

        self.fire_all_signals()
    
    def fire_all_signals(self):
        self.view_changed.emit()
        self.slice_pos_changed.emit()
        self.sd_changed.emit()

    def on_rotation_request(self, rotation: SnappedRotation) -> None:
        self._current_scan_rotation_in_view_ref = rotation * self._current_scan_rotation_in_view_ref
        self.view_changed.emit()

    def on_apply_rotation_request(self) -> None:
        self.slice_pos.rotate_about_inplace(self.current_scan_rotation_in_view_ref.rotation, self.scan.center)

        self._sd.rotate_about_inplace(self.current_scan_rotation_in_view_ref.rotation, self.scan.center)

        self._scan = Scan(self.scan.voxel_size, self.scan.rotate_data(self.current_scan_rotation_in_view_ref))

        self._applied_scan_rotation_in_view_ref = self.current_scan_rotation_in_view_ref * self.applied_scan_rotation_in_view_ref
        self._current_scan_rotation_in_view_ref = SnappedRotation.identity()

        self.fire_all_signals()
    
    def on_move_slice_pos_request(self, direction: CardinalDirection, value: int):
        self._slice_pos.move(direction, value)
        self._slice_pos.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.slice_pos_changed.emit()

    def on_set_slice_pos_request(self, direction: CardinalDirection, value: int):
        self._slice_pos.move_to(direction, value)
        self._slice_pos.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.slice_pos_changed.emit()

    def on_switch_slice_pos_show_dir_request(self, direction: CardinalDirection):
        self._slice_pos_show_dir[direction.dir] = not self._slice_pos_show_dir[direction.dir]
        self.slice_pos_changed.emit()

    def on_move_min_sd_request(self, direction: CardinalDirection, value:int):
        self._sd.min_point.move(direction, value)
        self._sd.min_point.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.sd_changed.emit()

    def on_move_max_sd_request(self, direction: CardinalDirection, value:int):
        self._sd.max_point.move(direction, value)
        self._sd.max_point.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.sd_changed.emit()

    def on_set_min_sd_request(self, direction: CardinalDirection, value: int):
        self._sd.min_point.move_to(direction, value)
        self._sd.min_point.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.sd_changed.emit()

    def on_set_max_sd_request(self, direction: CardinalDirection, value: int):
        self._sd.max_point.move_to(direction, value)
        self._sd.max_point.move_back_in_bounds(direction, 0, self.scan.shape[direction.dir] - 1)

        self.sd_changed.emit()

    def on_switch_sd_show_request(self):
        self._sd_show = not self._sd_show
        self.sd_changed.emit()

    def change_sd_type_request(self, type: SamplingType):
        self.sd.type = type

        self.sd_changed.emit()

    def on_add_grid_divisions_request(self, direction: CardinalDirection, value: int):
        self.sd.add_grid_divisions(direction, value)

        self.sd_changed.emit()

    def on_set_grid_divisions_request(self, direction: CardinalDirection, value: int):
        self.sd.set_grid_divisions(direction, value)

        self.sd_changed.emit()

    def on_switch_grid_show_request(self):
        self._grid_show = not self._grid_show
        self.sd_changed.emit()


class Mode(str, Enum):
    RESET = "reset"
    RESUME = "resume"
    SILENT = "silent"


@dataclass(frozen=True)
class AppConfig:
    input_dir: Path
    output_dir: Path
    mode: Mode
    autosave_interval_ms: int = 500


class CTidyStudio(QMainWindow):
    def __init__(self, scan: Scan, input_dir: Path, output_dir: Path, mode: "Mode") -> None:
        super().__init__()

        self._app_config = AppConfig(input_dir, output_dir, mode)

        self._build_app_state(scan)

        self._build_slice_views()
        self._build_ui()

        self.app_state.fire_all_signals()

    def _build_app_state(self, scan: Scan) -> None:
        self.app_state = AppState(scan)

        if self._app_config.mode == Mode.RESUME:
            self.app_state.load(self._app_config.input_dir / "app_state.json")

        self._build_save_connections()

    def _build_save_connections(self) -> None:
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(partial(self.app_state.save, self._app_config.input_dir))

        self.app_state.view_changed.connect(self._save_timer.start)
        self.app_state.slice_pos_changed.connect(self._save_timer.start)
        self.app_state.sd_changed.connect(self._save_timer.start)

    def _build_slice_views(self) -> None:

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

        right_container = self._build_scroll_area()
        
        main_layout.addWidget(left_container, 2)
        main_layout.addWidget(right_container, 1)

    def _build_scroll_area(self) -> QScrollArea:
        right_container = QScrollArea()
        right_container.setFixedWidth(470)
        right_container.setWidgetResizable(True)
        right_container.setFrameShape(QFrame.NoFrame)
        right_container.setObjectName("rightScrollArea")

        right_container.setStyleSheet("""
        QScrollArea#rightScrollArea {
            background: #2b2b2b;
            border: 1px solid #696969;
            border-radius: 26px;
        }

        QScrollArea#rightScrollArea > QWidget > QWidget {
            background: transparent;
        }

        /* Vertical scrollbar */
        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            border: none;
        }

        QScrollBar::handle:vertical {
            background-color: #3a3a3a;
            border: 1px solid #666;
            min-height: 10px;
            margin: 15px 2px 15px 2px
        }

        QScrollBar::handle:vertical:hover {
            background: #4a6fa5;
            border: 1px solid #7aa2d6;
        }
                                      
        QScrollBar::handle:vertical:pressed {
            background-color: #34527a;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: transparent;
        }
        """)

        # Inner scroll content widget
        scroll_content = QWidget()
        right_layout = QVBoxLayout(scroll_content)
        right_layout.setAlignment(Qt.AlignTop)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(10)

        right_layout.addWidget(self._create_apply_rotation_button(scroll_content))
        right_layout.addWidget(self._create_slice_pos_controls(scroll_content))
        right_layout.addWidget(self._create_sampling_domain_controls_panel(scroll_content))
        
        right_container.setWidget(scroll_content)

        return right_container

    def _create_apply_rotation_button(self, parent: QObject) -> QPushButton:
        btn = QPushButton()
        btn.clicked.connect(self.app_state.on_apply_rotation_request)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedHeight(32)

        btn.setText("Apply rotation")

        btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: white;
                border: 1px solid #666;
                border-radius: 16px;
                padding: 6px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4a6fa5;
                border: 1px solid #7aa2d6;
            }
            QPushButton:pressed {
                background-color: #34527a;
            }
        """)

        return btn

    @staticmethod
    def _create_base_frame(parent: QObject) -> tuple[QFrame, QLayout]:
        frame = QFrame(parent = parent)
        frame.setStyleSheet("""
            QFrame {
                background: #353535;
                border: 1px solid #696969;
                border-radius: 16px;
            }
                            
        QLabel {
            color: white;
            border: none;
            background: transparent;
        }
        """)

        layout = QVBoxLayout(frame)
        layout.setSpacing(0)
        layout.setContentsMargins(10, 6, 10, 10)

        return frame, layout
    
    @staticmethod
    def _create_increment_control(parent: QObject, binding: "IncrementControlBinding") -> "IncrementControl":
        if binding.type == "small":
            control = SmallIncrementControl(parent)
        elif binding.type == "normal":  
            control = IncrementControl(parent)
        else :
            raise ValueError(f"Unknown increment control type: {binding.type!r}")

        control.increment_requested.connect(binding.on_increment)
        control.value_submitted.connect(binding.on_submit)
        
        binding.refresh_signal.connect(lambda: control.set_value(binding.read_value()))

        return control

    @staticmethod
    def _create_show_button(text: str, action: Callable, update_signal: Signal, Color: QColor, is_shown: Callable[[], bool]) -> QPushButton:
        btn = QPushButton()
        btn.clicked.connect(action)
        btn.setFixedWidth(95)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)

        def update_btn() -> None:
            if is_shown():
                btn.setText(f"Hide {text}")

                btn.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {Color.name()};
                            color: white;
                            border: 1px solid #666;
                            border-radius: 6px;
                            padding: 6px 10px;
                            font-size: 12px;
                        }}
                        QPushButton:hover {{
                            background-color: {Color.darker(130).name()};
                            border: 1px solid #7aa2d6;
                        }}
                        QPushButton:pressed {{
                            background-color: {Color.name()};
                        }}
                    """)
                
            else:
                btn.setText(f"Show {text}")

                btn.setStyleSheet("""
                        QPushButton {
                            background-color: #3a3a3a;
                            color: white;
                            border: 1px solid #666;
                            border-radius: 6px;
                            padding: 6px 10px;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            background-color: #4a6fa5;
                            border: 1px solid #7aa2d6;
                        }
                        QPushButton:pressed {
                            background-color: #34527a;
                        }
                    """)
            
        update_signal.connect(update_btn)

        return btn

    def _create_slice_pos_control(self, direction: CardinalDirection, parent: QObject) -> QHBoxLayout:
        signal = self.app_state.slice_pos_changed
        
        layout = QHBoxLayout()
        layout.setSpacing(5)

        btn = self._create_show_button(
            f"{direction} Slice", 
            partial(self.app_state.on_switch_slice_pos_show_dir_request, direction), 
            signal, 
            direction.associated_color, 
            lambda: self.app_state.slice_pos_show_dir[direction.dir]
            )
        
        binding = IncrementControlBinding(
            "normal",
            partial(self.app_state.on_move_slice_pos_request, direction),
            partial(self.app_state.on_set_slice_pos_request, direction),
            signal,
            lambda: self.app_state.slice_pos.coord[direction.dir]
        )

        increment_button = self._create_increment_control(parent, binding)
        
        layout.addWidget(btn, 1)
        layout.addWidget(increment_button, 4)

        return layout

    def _create_slice_pos_controls(self, parent: QObject) -> QFrame:
        frame, layout = self._create_base_frame(parent)

        label = QLabel("Slice position")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        layout.addSpacing(5)

        layout.addLayout(self._create_slice_pos_control(CardinalDirection.X, frame))
        layout.addSpacing(5)
        layout.addLayout(self._create_slice_pos_control(CardinalDirection.Y, frame))
        layout.addSpacing(5)
        layout.addLayout(self._create_slice_pos_control(CardinalDirection.Z, frame))

        return frame

    def _create_sampling_domain_control(self, direction: CardinalDirection, parent: QObject) -> QLayout:
        signal = self.app_state.sd_changed

        layout = QVBoxLayout()
        layout.setSpacing(2)

        min_layout = QHBoxLayout()
        min_layout.setSpacing(5)
        layout.addLayout(min_layout)

        max_layout = QHBoxLayout()
        max_layout.setSpacing(5)
        layout.addLayout(max_layout)

        min_label = QLabel(f"Min. {direction} bound")
        min_layout.addWidget(min_label, 1)
        max_label = QLabel(f"Max. {direction} bound")
        max_layout.addWidget(max_label, 1)

        for label in [min_label, max_label]:
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedWidth(95)

        min_binding = IncrementControlBinding(
            "normal",
            partial(self.app_state.on_move_min_sd_request, direction),
            partial(self.app_state.on_set_min_sd_request, direction),
            signal,
            lambda: self.app_state.sd.min_point.coord[direction.dir]
        )
        min_layout.addWidget(self._create_increment_control(parent, min_binding), 4)

        max_binding = IncrementControlBinding(
            "normal",
            partial(self.app_state.on_move_max_sd_request, direction),
            partial(self.app_state.on_set_max_sd_request, direction),
            signal,
            lambda: self.app_state.sd.max_point.coord[direction.dir]
        )
        max_layout.addWidget(self._create_increment_control(parent, max_binding), 4)

        return layout

    def _create_sampling_domain_controls(self, parent: QObject) -> QLayout:
        layout = QVBoxLayout()

        layout.addLayout(self._create_sampling_domain_control(CardinalDirection.X, parent))
        layout.addSpacing(5)
        layout.addLayout(self._create_sampling_domain_control(CardinalDirection.Y, parent))
        layout.addSpacing(5)
        layout.addLayout(self._create_sampling_domain_control(CardinalDirection.Z, parent))

        return layout

    def _create_grid_divisions_control(self, parent: QObject) -> QLayout:
        signal = self.app_state.sd_changed

        layout = QVBoxLayout()
        layout.setSpacing(5)

        type_layout = QHBoxLayout()
        layout.setSpacing(5)
        layout.addLayout(type_layout)

        def _create_type_button(type: SamplingType, update_signal = Signal) -> QPushButton:
            btn = QPushButton()
            btn.clicked.connect(partial(self.app_state.change_sd_type_request, type))
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setText(type.value)

            def update_btn() -> None:
                if self.app_state.sd.type == type:
                    btn.setEnabled(False)
                    btn.setCursor(Qt.ArrowCursor)
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #4a6fa5;
                            color: white;
                            border: 1px solid #666;
                            border-radius: 6px;
                            padding: 6px 10px;
                            font-size: 12px;
                        }
                    """)
                
                else:
                    btn.setEnabled(True)
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #3a3a3a;
                            color: white;
                            border: 1px solid #666;
                            border-radius: 6px;
                            padding: 6px 10px;
                            font-size: 12px;
                        }
                        QPushButton:hover {
                            background-color: #34527a;
                            border: 1px solid #7aa2d6;
                        }
                        QPushButton:pressed {
                            background-color: #4a6fa5;
                        }
                    """)
            
            update_signal.connect(update_btn)

            return btn

        label = QLabel(f"Type")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedWidth(95)

        type_layout.addWidget(label, 1)
        type_layout.addWidget(_create_type_button(SamplingType.FULL, signal), 1)
        type_layout.addWidget(_create_type_button(SamplingType.UNIDIR, signal), 1)
        type_layout.addWidget(_create_type_button(SamplingType.UNIDIR_AUTO, signal), 1)
        type_layout.addWidget(_create_type_button(SamplingType.BIDIR, signal), 1)
        
        division_layout = QHBoxLayout()
        division_layout.setSpacing(5)
        layout.addLayout(division_layout)

        btn = self._create_show_button(
            f"grid",
            self.app_state.on_switch_grid_show_request,
            signal,
            GRID_COLOR,
            lambda: self.app_state.grid_show
            )

        division_layout.addWidget(btn, 1)

        for direction in [CardinalDirection.X, CardinalDirection.Y, CardinalDirection.Z]:
            binding = IncrementControlBinding(
                "small",
                partial(self.app_state.on_add_grid_divisions_request, direction),
                partial(self.app_state.on_set_grid_divisions_request, direction),
                signal,
                lambda direction = direction: self.app_state.sd.grid_divisions[direction.dir]
            )

            increment_button = self._create_increment_control(parent, binding)

            division_layout.addWidget(increment_button, 1.3333)

        return layout

    def _create_sampling_domain_controls_panel(self, parent: QObject) -> QFrame:
        frame, layout = self._create_base_frame(parent)

        label = QLabel("Sampling domain controls")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        layout.addSpacing(5)

        btn = self._create_show_button("DOI", self.app_state.on_switch_sd_show_request, self.app_state.sd_changed, SD_COLOR, lambda: self.app_state.sd_show)

        layout.addWidget(btn)

        layout.addSpacing(5)

        layout.addLayout(self._create_sampling_domain_controls(frame))

        layout.addSpacing(10)

        label = QLabel("Grid divisions")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        layout.addSpacing(5)

        layout.addLayout(self._create_grid_divisions_control(frame))

        return frame

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
    def snapped_rotation(self):
        return self._view_orientation.rotate(self.app_state.current_scan_rotation_in_view_ref.inv()).rotation.inv()

    def __init__(self, app_state: AppState, view_orientation: Orientation) -> None:
        super().__init__()

        self.app_state = app_state
        self._view_orientation = view_orientation
        self._view_center = Point(np.array([0, 0, 0])) # In scan coordinates

        self._build_view()
        self._build_dependencies()
        self._build_conections()

        self.setMinimumSize(300, 300)

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

        self._rectangle_sd_outline = QGraphicsRectItem(parent = self._pixmap_item)

        self._update_grid_lines = self._make_grid_updater(self._pixmap_item)

    def _build_conections(self):
        self.rotation_request.connect(self.app_state.on_rotation_request)

        self.app_state.view_changed.connect(self._update_view)
        self.app_state.view_changed.connect(self._update_slice_lines)
        self.app_state.view_changed.connect(self._update_sd_outline)
        self.app_state.view_changed.connect(self._update_grid_lines)

        self.app_state.slice_pos_changed.connect(self._update_view)
        self.app_state.slice_pos_changed.connect(self._update_slice_lines)

        self.app_state.sd_changed.connect(self._update_sd_outline)
        self.app_state.sd_changed.connect(self._update_grid_lines)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        
        self._update_slice_lines()
        self._update_sd_outline()
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

        ## Drawings

        painter.setPen(QPen(Qt.GlobalColor.black, 1))
        painter.setBrush(QBrush(Qt.GlobalColor.white))

        # Scale line
        w = self.viewport().width()
        h = self.viewport().height()

        bar_width = int(w * self.BAR_WIDTH_RATIO)
        bar_height = int(h * self.BAR_HEIGHT_RATIO)

        horizontal_margin = int(w * self.BAR_MARGIN_RATIO)
        vertical_margin = int(h * self.BAR_MARGIN_RATIO)

        x = w - horizontal_margin - bar_width
        y = h - vertical_margin

        painter.drawRect(x, y, bar_width, bar_height)

        # Axis
        view_orientation_in_view_coord = self._view_orientation.rotate(self.app_state.current_scan_rotation_in_view_ref.inv())

        # Right axis
        horizontal_arrow = QPolygonF([
            QPointF(horizontal_margin, y),
            QPointF(horizontal_margin + bar_width, y),
            QPointF(horizontal_margin + bar_width, y + bar_height),
            QPointF(horizontal_margin + bar_width + bar_height * 2, y - bar_height / 2),
            QPointF(horizontal_margin + bar_width, y - 2 * bar_height),
            QPointF(horizontal_margin + bar_width, y - bar_height),
            QPointF(horizontal_margin, y - bar_height),
        ])

        painter.setBrush(QBrush(view_orientation_in_view_coord.right.associated_color))
        painter.drawPolygon(horizontal_arrow)

        # Up axis
        vertical_arrow = QPolygonF([
            QPointF(vertical_margin, h - horizontal_margin),
            QPointF(vertical_margin, h - horizontal_margin-bar_width),
            QPointF(vertical_margin - bar_height, h - horizontal_margin - bar_width),
            QPointF(vertical_margin + bar_height / 2, h - horizontal_margin - bar_width - bar_height * 2),
            QPointF(vertical_margin + 2 * bar_height, h - horizontal_margin - bar_width),
            QPointF(vertical_margin + bar_height, h - horizontal_margin - bar_width),
            QPointF(vertical_margin + bar_height, h - horizontal_margin),
        ])

        painter.setBrush(QBrush(view_orientation_in_view_coord.up.associated_color))
        painter.drawPolygon(vertical_arrow)

        ## Text
        def draw_text(x: float, y: float, text: str, color: QColor):
            # black outline
            painter.setPen(Qt.GlobalColor.black)
            painter.drawText(x - 1, y, text)
            painter.drawText(x + 1, y, text)
            painter.drawText(x, y - 1, text)
            painter.drawText(x, y + 1, text)

            painter.setPen(color)
            painter.drawText(x, y, text)

        # Scale text
        real_size = self.app_state.scan.voxel_size / 1000 * bar_width / self.transform().m11()
        text = _to_si(real_size)

        font = QFont()
        font.setPointSizeF(bar_width / 4)
        painter.setFont(font)

        fm = painter.fontMetrics()
        text_width = fm.boundingRect(text).width()

        text_x = x + (bar_width - text_width) / 2
        text_y = y - bar_height * 2

        draw_text(text_x, text_y, text, Qt.GlobalColor.white)

        # Right axis text
        text_x = horizontal_margin + bar_width + bar_height * 3
        text_y = y - (bar_height - fm.ascent() + fm.descent()) / 2

        draw_text(text_x, text_y, str(view_orientation_in_view_coord.right), view_orientation_in_view_coord.right.associated_color)

        # Up axis text
        text_x = vertical_margin + (bar_height - fm.boundingRect(str(view_orientation_in_view_coord.up)).width()) / 2
        text_y =  h - horizontal_margin - bar_width - bar_height * 3

        draw_text(text_x, text_y, str(view_orientation_in_view_coord.up), view_orientation_in_view_coord.up.associated_color)

        painter.restore()

    def _update_view(self):
        rotated_data = self.app_state.scan.rotate_data(self.snapped_rotation)
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
        return point.rotate_about(self.snapped_rotation.rotation, self.app_state.scan.center)
    
    def _view_to_global_coord(self, point: Point) -> Point:
        return point.rotate_about(self.snapped_rotation.rotation.inv(), self._global_to_view_coord(self.app_state.scan.center))
    
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
        self._update_line_thickness()

    def _update_slice_lines(self) -> None:
        view_orientation_in_view_coord = self._view_orientation.rotate(self.app_state.current_scan_rotation_in_view_ref.inv())

        slice_pos_in_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(self.app_state.slice_pos))
        
        self._horizontal_slice_line.setLine(0, slice_pos_in_pixmap_coord.y(), self._pixmap_item.boundingRect().width(), slice_pos_in_pixmap_coord.y())
        self._horizontal_slice_line.setPen(QPen(view_orientation_in_view_coord.up.associated_color, 1))
        self._horizontal_slice_line.setZValue(12)
        
        self._vertical_slice_line.setLine(slice_pos_in_pixmap_coord.x(), 0, slice_pos_in_pixmap_coord.x(), self._pixmap_item.boundingRect().height())
        self._vertical_slice_line.setPen(QPen(view_orientation_in_view_coord.right.associated_color, 1))
        self._vertical_slice_line.setZValue(12)
        self._update_line_thickness()

        self._horizontal_slice_line.setVisible(self.app_state.slice_pos_show_dir[view_orientation_in_view_coord.up.dir])
        self._vertical_slice_line.setVisible(self.app_state.slice_pos_show_dir[view_orientation_in_view_coord.right.dir])

    def _update_line_thickness(self) -> None:
        min_viewport_dimension = min(self.viewport().height(), self.viewport().width()) / self.transform().m11()
        line_thickness = min_viewport_dimension * self.SLICE_LINE_RATIO

        for item in self._pixmap_item.childItems():
            if isinstance(item, (QGraphicsLineItem, QGraphicsRectItem)):
                item.setPen(QPen(item.pen().color(), line_thickness))

            if isinstance(item, QGraphicsEllipseItem):
                center = item.rect().center()
                item.setRect(center.x() - line_thickness, center.y() - line_thickness, line_thickness*2, line_thickness*2)

    def _update_sd_outline(self) -> None:
        min_point_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(self.app_state.sd.min_point))
        max_point_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(self.app_state.sd.max_point))

        self._rectangle_sd_outline.setRect(QRectF(min_point_pixmap_coord, max_point_pixmap_coord).normalized())
        self._rectangle_sd_outline.setPen(QPen(SD_COLOR, 1))
        self._update_line_thickness()

        self._rectangle_sd_outline.setZValue(10)
        self._rectangle_sd_outline.setVisible(self.app_state.sd_show)

    def _make_grid_updater(self, parent: QGraphicsPixmapItem) -> Callable:
        grid_lines: list[QGraphicsLineItem | QGraphicsEllipseItem] = []

        def update_grid_lines() -> None:
            for obj in grid_lines:
                if obj is not None:
                    self.scene.removeItem(obj)

            grid_lines.clear()

            if self.app_state.grid_show:
                for start, end in self.app_state.sd.grid_lines_by_extremities():
                    start_in_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(start))
                    end_in_pixmap_coord = self._view_to_pixmap_coord(self._global_to_view_coord(end))

                    if start_in_pixmap_coord == end_in_pixmap_coord:
                        obj = QGraphicsEllipseItem(start_in_pixmap_coord.x()-1, start_in_pixmap_coord.y()-1, 2, 2, parent)
                        obj.setPen(Qt.PenStyle.NoPen)
                        obj.setBrush(QBrush(GRID_COLOR))
                        obj.setZValue(11)

                    else:
                        obj = QGraphicsLineItem(QLineF(start_in_pixmap_coord, end_in_pixmap_coord), parent)
                        obj.setPen(QPen(GRID_COLOR, 1))
                        obj.setZValue(8)

                    grid_lines.append(obj)

                self._update_line_thickness()

        return update_grid_lines

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

        self.rotation_request.emit(direction.snapped_rotation_around_direction)
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
    type: Literal["small", "normal"]
    on_increment: Callable[[int], None]
    on_submit: Callable[[int], None]
    refresh_signal: Signal
    read_value: Callable[[], int]


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
                font-size: 12px;
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

        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def _on_clicked(self):
        self._on_increment_signal.emit(self._increment)


class IncrementControl(QWidget):
    increment_requested = Signal(int)
    value_submitted = Signal(int)

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)

        self._build_dependencies()

    def _build_dependencies(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._decrease_100_btn = IncrementButton("---", -100, self.increment_requested, parent = self)
        self._decrease_10_btn = IncrementButton("--", -10, self.increment_requested, parent = self)
        self._decrease_1_btn = IncrementButton("-", -1, self.increment_requested, parent = self)

        self._editable_display = QLineEdit(parent = self)
        self._editable_display.setAlignment(Qt.AlignCenter)
        self._editable_display.returnPressed.connect(self._on_value_submitted)

        self._increase_1_btn = IncrementButton("+", 1, self.increment_requested, parent = self)
        self._increase_10_btn = IncrementButton("++", 10, self.increment_requested, parent = self)
        self._increase_100_btn = IncrementButton("+++", 100, self.increment_requested, parent = self)

        layout.addWidget(self._decrease_100_btn, 3)
        layout.addWidget(self._decrease_10_btn, 2)
        layout.addWidget(self._decrease_1_btn, 1)
        layout.addWidget(self._editable_display, 4)
        layout.addWidget(self._increase_1_btn, 1)
        layout.addWidget(self._increase_10_btn, 2)
        layout.addWidget(self._increase_100_btn, 3)

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
                font-size: 12px;
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
        self._editable_display.setText(str(value))


class SmallIncrementControl(QWidget):
    increment_requested = Signal(int)
    value_submitted = Signal(int)

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)

        self._build_dependencies()

    def _build_dependencies(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._decrease_1_btn = IncrementButton("-", -1, self.increment_requested, parent = self)

        self._editable_display = QLineEdit(parent = self)
        self._editable_display.setAlignment(Qt.AlignCenter)
        self._editable_display.returnPressed.connect(self._on_value_submitted)

        self._increase_1_btn = IncrementButton("+", 1, self.increment_requested, parent = self)

        layout.addWidget(self._decrease_1_btn, 1)
        layout.addWidget(self._editable_display, 4)
        layout.addWidget(self._increase_1_btn, 1)

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
                font-size: 12px;
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
        self._editable_display.setText(str(value))


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
        window = CTidyStudio(scan, input_dir, output_dir, mode)
        window.show()
        exit_code = app.exec()

    if exit_code == 0:
        console.print("[green]✔ Scan handling complete[/green]")

    return exit_code