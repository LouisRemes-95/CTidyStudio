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

    def quantization_to_uint8(self) -> None:
        data = self.data
        self.data = ((data - data.min()) / (data.max() - data.min()) * 255).astype(np.uint8)

    def rot90(self, rotation_axis: tuple[int, int]) -> None:
        self.data = np.rot90(self.data, 1, rotation_axis)


def load_tif_stack(path: Path, voxel_size: float) -> Scan:
    files = sorted(path.glob("*.tif"))
    if not files:
        raise ValueError(f"No .tif files found in {path}")
    return Scan(voxel_size, np.stack([tifffile.imread(f) for f in files]))
