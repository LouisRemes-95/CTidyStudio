from pathlib import Path
from enum import Enum

import tifffile
import numpy as np
from scipy.spatial.transform import Rotation as R
from PySide6.QtCore import QRect, QPoint


class CardinalDirection(Enum):
    X  = (1, 0, 0)
    Y  = (0, 1, 0)
    Z  = (0, 0, 1)
    X_ = (-1, 0, 0)
    Y_ = (0, -1, 0)
    Z_ = (0, 0, -1)

    def __init__(self, x: int, y: int, z: int):
        self._vec = np.array((x, y, z), dtype=int)
        self._direction_index = np.nonzero(self._vec)[0][0]

    @property
    def vec(self):
        return self._vec

    @property
    def dir(self):
        return self._direction_index

    def __neg__(self) -> "CardinalDirection":
        opposites = {
            CardinalDirection.X: CardinalDirection.X_,
            CardinalDirection.Y: CardinalDirection.Y_,
            CardinalDirection.Z: CardinalDirection.Z_,
            CardinalDirection.X_: CardinalDirection.X,
            CardinalDirection.Y_: CardinalDirection.Y,
            CardinalDirection.Z_: CardinalDirection.Z,
        }
        return opposites[self]
    
    def rotating_plane(self) -> tuple[int, int]:
        plane = {
            CardinalDirection.X: (1, 2),
            CardinalDirection.Y: (0, 2),
            CardinalDirection.Z: (0, 1),
            CardinalDirection.X_: (2, 1),
            CardinalDirection.Y_: (2, 0),
            CardinalDirection.Z_: (1, 0),
        }
        return plane[self]
    
    def rotation(self) -> dict[str, object]:
        params = {
            CardinalDirection.X: {"seq": "x", "angles": 90, "degrees": True},
            CardinalDirection.Y: {"seq": "y", "angles": 90, "degrees": True},
            CardinalDirection.Z: {"seq": "z", "angles": 90, "degrees": True},
            CardinalDirection.X_: {"seq": "x", "angles": -90, "degrees": True},
            CardinalDirection.Y_: {"seq": "y", "angles": -90, "degrees": True},
            CardinalDirection.Z_: {"seq": "z", "angles": -90, "degrees": True},
        }
        return params[self]


class Orientation:
    def __init__(self, forward: CardinalDirection, up: CardinalDirection) -> None:
        if np.dot(forward.vec, up.vec) != 0:
            raise ValueError("forward and up must be perpendicular")
        self.forward = forward
        self.up = up
        self._compute_right()

    def _compute_right(self) -> None:
        self.right = CardinalDirection(tuple(np.cross(self.forward.vec, self.up.vec)))


class Scan:
    def __init__(self, voxel_size: float, data: np.ndarray) -> None:
        if voxel_size <= 0:
            raise ValueError("voxel size must be positive")
        self.voxel_size = voxel_size

        if not isinstance(data, np.ndarray):
            raise TypeError("data must be a numpy ndarray")
        if data.ndim != 3:
            raise ValueError(f"data must be 3D (z, y, x), got {data.ndim}D")
        self.data = data
        self.compute_center()

    @property
    def shape(self):
        return self.data.shape

    def quantization_to_uint8(self) -> None:
        data = self.data
        data_min = data.min()
        data_max = data.max()

        if data_max == data_min:
            self.data = np.zeros(data.shape, dtype=np.uint8)
            return

        self.data = ((data - data_min) / (data_max - data_min) * 255).astype(np.uint8)

    def rot90(self, rotation_axis: CardinalDirection) -> None:
        self.data = np.rot90(self.data, 1, rotation_axis.rotating_plane())
        self.compute_center()

    def compute_center(self):
        self.center = (np.array(self.data.shape)-1)/2

    def slice(self, axis: int, index: int):
        slc = [slice(None)] * self.data.ndim
        slc[axis] = index
        return self.data[tuple(slc)]


class DomainOfInterest:
    def __init__(self, shape: tuple[int, int, int]) -> None:
        self.origin = np.array([0, 0, 0])
        self.opposit_point = np.array([shape[0]-1, shape[1]-1, shape[2]-1])
        self.local_ref = np.array([[1, 0, 0], [0, 1, 0],[0, 0, 1]])

    def rotate_and_translate(self, direction: CardinalDirection, source_pivot: np.ndarray, target_pivot: np.ndarray) -> None:
        self.origin = np.rint(rotate_and_translate_point(self.origin, direction, source_pivot, target_pivot))
        self.opposit_point = np.rint(rotate_and_translate_point(self.opposit_point, direction, source_pivot, target_pivot))

        rotation = R.from_euler(**direction.rotation())
        self.local_ref = rotation.apply(self.local_ref)

    def view_box(self, orientation: Orientation, pixmap_height: int) -> QRect:
        origin_pixmap_coord = view_to_pixmap_coord(self.origin, orientation, pixmap_height)
        opposit_pixmap_coord = view_to_pixmap_coord(self.opposit_point, orientation, pixmap_height)

        if origin_pixmap_coord.x() > opposit_pixmap_coord.x():
            min_x = opposit_pixmap_coord.x()
            opposit_pixmap_coord.setX(origin_pixmap_coord.x())
            origin_pixmap_coord.setX(min_x)

        if origin_pixmap_coord.y() > opposit_pixmap_coord.y():
            min_x = opposit_pixmap_coord.y()
            opposit_pixmap_coord.setY(origin_pixmap_coord.y())
            origin_pixmap_coord.setY(min_x)

        return QRect(origin_pixmap_coord, opposit_pixmap_coord)
    
    def move_origin(self, local_move_direction: CardinalDirection, increment: int):
        movement = local_move_direction.vec @ self.local_ref
        self.origin = self.origin + movement.astype(int) * increment

    def set_origin_component(self, local_move_direction: CardinalDirection, value: int):
        self.origin[local_move_direction.vec @ self.local_ref == 1] = value
    

def rotate_and_translate_point(point: np.ndarray, direction: CardinalDirection, source_pivot: np.ndarray, target_pivot: np.ndarray) -> np.ndarray:
    if point.shape != (3,) or source_pivot.shape != (3,) or target_pivot.shape != (3,):
        raise ValueError("point, source_pivot, and target_pivot must all have shape (3,)")

    rotation = R.from_euler(**direction.rotation())

    return (rotation.apply((point - source_pivot)) + target_pivot)


def view_to_pixmap_coord(point: np.ndarray, orientation: Orientation, pixmap_height: int) -> QPoint:
    return QPoint(np.dot(orientation.right.vec, point), pixmap_height - 1 - np.dot(orientation.up.vec, point))


def pixmap_to_view_coord(point: QPoint, orientation: Orientation, pixmap_height: int, slice_index: int) -> np.ndarray:
    return point.x() * orientation.right.vec + (pixmap_height - point.y()) * orientation.up.vec + slice_index * orientation.forward.vec


def load_tif_stack(path: Path, voxel_size: float) -> Scan:
    files = sorted(path.glob("*.tif"))
    if not files:
        raise ValueError(f"No .tif files found in {path}")

    slices: list[np.ndarray] = []
    expected_shape: tuple[int, int] | None = None

    for file in files:
        slice_data = tifffile.imread(file)

        if not isinstance(slice_data, np.ndarray):
            raise TypeError(f"Unsupported TIFF content in {file}: expected a NumPy array")
        if slice_data.ndim != 2:
            raise ValueError(
                f"Unsupported TIFF image shape in {file}: expected 2D slice, got {slice_data.ndim}D"
            )
        if not np.issubdtype(slice_data.dtype, np.number) or np.issubdtype(
            slice_data.dtype, np.complexfloating
        ):
            raise TypeError(
                f"Unsupported TIFF dtype in {file}: expected a real numeric array, got {slice_data.dtype}"
            )

        if expected_shape is None:
            expected_shape = slice_data.shape
        elif slice_data.shape != expected_shape:
            raise ValueError(
                f"Mismatched TIFF slice shape in {file}: expected {expected_shape}, got {slice_data.shape}"
            )

        slices.append(slice_data)

    return Scan(voxel_size, np.stack(slices))
