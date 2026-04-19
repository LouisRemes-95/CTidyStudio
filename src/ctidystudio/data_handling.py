from pathlib import Path
from enum import Enum

import tifffile
import numpy as np
from scipy.spatial.transform import Rotation as R


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

    def rot90(self, rotation_axis: tuple[int, int]) -> None:
        self.data = np.rot90(self.data, 1, rotation_axis)
        self.compute_center()

    def compute_center(self):
        self.center = (np.array(self.data.shape)-1)/2


class Direction(tuple, Enum):
    X = (1, 2)
    Y = (0, 2)
    Z = (0, 1)
    X_ = (2, 1)
    Y_ = (2, 0)
    Z_ = (1, 0)

    def __neg__(self):
        opposites = {
            Direction.X: Direction.X_,
            Direction.Y: Direction.Y_,
            Direction.Z: Direction.Z_,
            Direction.X_: Direction.X,
            Direction.Y_: Direction.Y,
            Direction.Z_: Direction.Z,
        }
        return opposites[self]
    
    def params(self):
        params = {
            Direction.X: {"seq": "x", "angles": 90, "degrees": True},
            Direction.Y: {"seq": "y", "angles": 90, "degrees": True},
            Direction.Z: {"seq": "z", "angles": 90, "degrees": True},
            Direction.X_: {"seq": "x", "angles": -90, "degrees": True},
            Direction.Y_: {"seq": "y", "angles": -90, "degrees": True},
            Direction.Z_: {"seq": "z", "angles": -90, "degrees": True},
        }
        return params[self]


class DomainOfInterest:
    def __init__(self, shape: tuple[int, int, int]):
        self._origin = np.array([[0, 0, 0]])
        self._extend_vectors = np.ndarray([[shape[0]-1, 0, 0], [0, shape[1]-1, 0], [0, shape[2]-1, 0]])

    def rotate_around(self, pivot: np.ndarray, direction: Direction):
        assert pivot.shape == (1,3)

        rot = R.from_euler(**direction.params())
        
        self._origin = rot.apply((self._origin - pivot)) + pivot
        self._extend_vectors = rot.apply(self._extend_vectors)



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
