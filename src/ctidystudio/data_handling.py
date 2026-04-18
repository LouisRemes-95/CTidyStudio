from pathlib import Path

import tifffile
import numpy as np


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
        self.center = (np.array(self.data.size)-1)/2


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
