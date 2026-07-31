from pathlib import Path
from dataclasses import dataclass, field, InitVar
from enum import Enum
from collections import deque

from scipy.spatial.transform import Rotation
import numpy as np
import tifffile
from PySide6.QtGui import (
    QColor,
)


class Point:
    def __init__(self, coord: np.ndarray):
        if coord.shape != (3,):
            raise ValueError("The coord given to a point should be a (3,) np.ndarray")

        self._set_coord(coord)

    def _set_coord(self, coord: np.ndarray) -> None:
        self._coord = coord.copy()

    @property
    def coord(self) -> np.ndarray:
        return self._coord

    @property
    def int_coord(self) -> np.ndarray:
        return np.rint(self.coord).astype(int)

    def rotate_about(self, rotation: Rotation, point: "Point | None" = None) -> "Point":
        if point is None:
            point = Point(np.zeros(3))

        return Point(rotation.apply(self.coord) + np.abs(rotation.apply(point.coord)) - rotation.apply(point.coord))

    def rotate_about_inplace(self, rotation: Rotation, point: "Point | None" = None) -> None:
        self._set_coord(self.rotate_about(rotation, point).coord)

    def move(self, direction: "CardinalDirection", value: int) -> None:
        value = value if direction.vec[direction.dir] > 0 else -value

        coord = self.coord.copy()
        coord[direction.dir] += value
        self._set_coord(coord)

    def move_to(self, direction: "CardinalDirection", value: int) -> None:
        value = value if direction.vec[direction.dir] > 0 else -value

        coord = self.coord.copy()
        coord[direction.dir] = value
        self._set_coord(coord)

    def move_back_in_bounds(self, direction: "CardinalDirection", lower: float, upper: float) -> None:
        coord = self.coord.copy()
        coord[direction.dir] = max(coord[direction.dir], lower)
        coord[direction.dir] = min(coord[direction.dir], upper)
        self._set_coord(coord)


class IntPoint(Point):
    def _set_coord(self, coord: np.ndarray) -> None:
        self._coord = np.rint(coord).astype(int)


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

    def __str__(self):
        return f"-{self.name[0]}" if self.name.endswith("_") else self.name

    @property
    def vec(self) -> np.ndarray:
        return self._vec

    @property
    def dir(self) -> int:
        return self._direction_index
    
    @property
    def rotation_around_direction(self) -> Rotation:
        rotations = {
            CardinalDirection.X: Rotation.from_euler("x", 90, degrees = True),
            CardinalDirection.Y: Rotation.from_euler("y", 90, degrees = True),
            CardinalDirection.Z: Rotation.from_euler("z", 90, degrees = True),
            CardinalDirection.X_: Rotation.from_euler("x", -90, degrees = True),
            CardinalDirection.Y_: Rotation.from_euler("y", -90, degrees = True),
            CardinalDirection.Z_: Rotation.from_euler("z", -90, degrees = True),
        }
        return rotations[self]
    
    @property
    def rotating_plane(self) -> tuple[int, int]:
        plane = {
            CardinalDirection.X: (1, 2),
            CardinalDirection.Y: (2, 0),
            CardinalDirection.Z: (0, 1),
            CardinalDirection.X_: (2, 1),
            CardinalDirection.Y_: (0, 2),
            CardinalDirection.Z_: (1, 0),
        }
        return plane[self]
    
    @property
    def associated_color(self) -> QColor:
        colors = {
            0: QColor("#1F77B4"),
            1: QColor("#FF7F0E"),
            2: QColor("#2CA02C"),
            }
        return colors[self.dir]

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

    def rotate(self, rotation: Rotation) -> "CardinalDirection":
        return CardinalDirection(tuple(np.rint(rotation.apply(self.vec)).astype(int)))


@dataclass(frozen=True)
class RotationKey:
    rotation: Rotation

    def _key(self) -> tuple[tuple[int, int, int], ...]:
        matrix = self.rotation.as_matrix()
        snapped = np.rint(matrix).astype(int)

        if not np.allclose(matrix, snapped, atol=1e-8):
            raise ValueError(
                f"Rotation is not a cardinal 90-degree rotation:\n{matrix}"
            )

        return tuple(tuple(row) for row in snapped)

    def __hash__(self) -> int:
        return hash(self._key())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RotationKey) and self._key() == other._key()


def _build_rotation_lookup() -> dict[RotationKey, list[CardinalDirection]]:
    lookup: dict[RotationKey, list[CardinalDirection]] = {RotationKey(Rotation.identity()): []}

    rotation_queue = deque([Rotation.identity()])

    while len(lookup) < 24:
        rotation = rotation_queue.popleft()

        for direction in CardinalDirection:
            new_rotation = direction.rotation_around_direction * rotation
            new_key = RotationKey(new_rotation)

            if new_key not in lookup:
                lookup[new_key] = lookup[RotationKey(rotation)] + [direction]
                rotation_queue.append(new_rotation)

    return lookup


ROTATION_LOOKUP = _build_rotation_lookup()


@dataclass(frozen=True)
class Orientation:
    forward: CardinalDirection
    up: CardinalDirection
    right: CardinalDirection = field(init=False)
    rotation: Rotation = field(init=False)

    def __post_init__(self) -> None:
        if np.dot(self.forward.vec, self.up.vec) != 0:
            raise ValueError("forward and up must be perpendicular")
        
        object.__setattr__(self, "right", CardinalDirection(tuple(np.rint(np.cross(self.forward.vec, self.up.vec)).astype(int))))

        object.__setattr__(self, "rotation", Rotation.from_matrix(np.column_stack((self.right.vec, self.up.vec, -self.forward.vec))))

    def rotate(self, rotation: Rotation) -> "Orientation":
        return Orientation(self.forward.rotate(rotation), self.up.rotate(rotation))


@dataclass(frozen=True)
class Scan:
    voxel_size: InitVar[float]
    data: InitVar[np.ndarray]

    _voxel_size: float = field(init=False)
    _data: np.ndarray = field(init=False)
    _center: Point = field(init=False)

    def __post_init__(self, voxel_size: float, data: np.ndarray) -> None:
        if voxel_size <= 0:
            raise ValueError("voxel size must be positive")

        if not isinstance(data, np.ndarray):
            raise TypeError("data must be a numpy ndarray")

        if data.ndim != 3:
            raise ValueError(f"data must be 3D (z, y, x), got {data.ndim}D")

        quantized = self.quantization_to_uint8(data)

        object.__setattr__(self, "_voxel_size", voxel_size)
        object.__setattr__(self, "_data", quantized)
        object.__setattr__(self, "_center", Point((np.array(quantized.shape) - 1) / 2))

    @property
    def voxel_size(self) -> float:
        return self._voxel_size

    @property
    def data(self) -> np.ndarray:
        return self._data

    @property
    def shape(self) -> tuple[int, ...]:
        return self._data.shape

    @property
    def center(self) -> Point:
        return self._center
    
    def rotate_data(self, rotation: Rotation) -> np.ndarray:
        rotation_sequence = ROTATION_LOOKUP[RotationKey(rotation)]

        rotated_data = self.data
        for direction in rotation_sequence:
            rotated_data = np.rot90(rotated_data, 1, direction.rotating_plane)

        return rotated_data

    @staticmethod
    def quantization_to_uint8(data: np.ndarray) -> np.ndarray:
        data_min = data.min()
        data_max = data.max()

        if data_max == data_min:
            return np.zeros(data.shape, dtype=np.uint8)

        return ((data - data_min) / (data_max - data_min) * 255).astype(np.uint8)
    
    @classmethod
    def from_tif_stack(cls, path: Path, voxel_size: float) -> "Scan":
        files = sorted(path.glob("*.tif"))
        if not files:
            raise ValueError(f"No .tif files found in {path}")

        slices: list[np.ndarray] = []
        expected_shape: tuple[int, int] | None = None

        for file in files:
            slice_data = tifffile.imread(file)

            if not isinstance(slice_data, np.ndarray):
                raise TypeError(f"{file}: expected NumPy array")

            if slice_data.ndim != 2:
                raise ValueError(f"{file}: expected 2D slice, got {slice_data.ndim}D")

            if not np.issubdtype(slice_data.dtype, np.number) or np.issubdtype(
                slice_data.dtype, np.complexfloating
            ):
                raise TypeError(f"{file}: unsupported dtype {slice_data.dtype}")

            if expected_shape is None:
                expected_shape = slice_data.shape
            elif slice_data.shape != expected_shape:
                raise ValueError(
                    f"{file}: expected shape {expected_shape}, got {slice_data.shape}"
                )

            slices.append(slice_data)

        volume = np.stack(slices)
        return cls(voxel_size, volume)

@dataclass
class Domain:
    min_point: IntPoint
    max_point: IntPoint

    def rotate_about(self, rotation: Rotation, point: "Point | None" = None) -> "Domain":
        return Domain(self.min_point.rotate_about(rotation, point), self.max_point.rotate_about(rotation, point))

    def rotate_about_inplace(self, rotation: Rotation, point: "Point | None" = None) -> None:
        self.min_point.rotate_about_inplace(rotation, point)
        self.max_point.rotate_about_inplace(rotation, point)

class SamplingType(str, Enum):
    FULL = "Full"
    UNIDIR = "Uni"
    UNIDIR_AUTO = "Uni auto"
    BIDIR = "Bi"

@dataclass
class SamplingDomain(Domain):
    # UnidirAuto, computes the voxel depth equal to the max X or Y dimension
    type: SamplingType = SamplingType.FULL
    grid_divisions: np.typing.NDArray[np.int_] = field(default_factory=lambda: np.zeros(3, dtype=int))
    # doi_size = number divisions making up the doi, if Unidir doi_size[1] = Z voxel depth
    doi_size: np.typing.NDArray[np.int_] = field(default_factory=lambda: np.zeros(3, dtype=int))
    seed: int = 0

    def add_grid_divisions(self, direction: CardinalDirection, value: int) -> None:
        self.grid_divisions[direction.dir] += value

        np.maximum(self.grid_divisions, 0, out=self.grid_divisions)

    def set_grid_divisions(self, direction: CardinalDirection, value: int) -> None:
        self.grid_divisions[direction.dir] = value

        np.maximum(self.grid_divisions, 0, out=self.grid_divisions)

    def grid_lines_by_extremities(self) -> list[tuple[IntPoint, IntPoint]]:
        x_linespacing, y_linespacing, z_linespacing = (np.linspace(min_coord, max_coord, divisions)
            for min_coord, max_coord, divisions in zip(self.min_point.coord, self.max_point.coord, self.grid_divisions + 2)
        )

        if type != SamplingType.BIDIR:
            x_coords, y_coords = np.meshgrid(x_linespacing, y_linespacing)

            min_points = [IntPoint(np.array([x, y, self.min_point.coord[2]])) for x, y in zip(x_coords.ravel(), y_coords.ravel())]
            max_points = [IntPoint(np.array([x, y, self.max_point.coord[2]])) for x, y in zip(x_coords.ravel(), y_coords.ravel())]

            return zip(min_points, max_points)
            
        else:
            pass


