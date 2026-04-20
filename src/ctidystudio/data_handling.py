from pathlib import Path
from enum import Enum

import tifffile
import numpy as np
from scipy.spatial.transform import Rotation as R
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QGraphicsPixmapItem


class CardinalDirection(Enum):
    X  = (1, 0, 0)
    Y  = (0, 1, 0)
    Z  = (0, 0, 1)
    X_ = (-1, 0, 0)
    Y_ = (0, -1, 0)
    Z_ = (0, 0, -1)

    def __init__(self, x: int, y: int, z: int):
        self._vec = np.array((x, y, z), dtype=int)

    @property
    def vec(self):
        return self._vec

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


class DomainOfInterest:
    def __init__(self, shape: tuple[int, int, int]) -> None:
        self._origin = np.array([0, 0, 0])
        self._extend_vectors = np.array([[shape[0]-1, 0, 0], [0, shape[1]-1, 0], [0, 0, shape[2]-1]])

    def rotate_around(self, pivot: np.ndarray, direction: CardinalDirection) -> None:
        assert pivot.shape == (3,)

        rot = R.from_euler(**direction.rotation())
        
        self._origin = (rot.apply((self._origin - pivot)) + pivot)
        self._extend_vectors = rot.apply(self._extend_vectors).astype(int)

    def view_box(self, orientation: Orientation, pixmap_height: int) -> QRect:
        h_pos = np.dot(orientation.right.vec, self._origin)
        v_pos = pixmap_height - np.dot(orientation.up.vec, self._origin)

        width = self._extend_vectors @ orientation.right.vec[:,None]
        assert np.count_nonzero(width) == 1
        width = width[width != 0][0]

        height = self._extend_vectors @ orientation.up.vec[:,None]
        assert np.count_nonzero(height) == 1
        height = height[height != 0][0]

        return QRect(h_pos, v_pos, width, -height)


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
