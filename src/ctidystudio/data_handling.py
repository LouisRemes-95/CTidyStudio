from pathlib import Path
from dataclasses import dataclass, field, InitVar
from enum import Enum
from collections import deque
from typing import Any, TypeAlias

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

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented

        return np.array_equal(self._coord, other._coord)
        
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

    def move_back_in_bounds_direction(self, direction: "CardinalDirection", lower: float, upper: float) -> None:
        coord = self.coord.copy()
        coord[direction.dir] = max(coord[direction.dir], lower)
        coord[direction.dir] = min(coord[direction.dir], upper)
        self._set_coord(coord)

    def move_back_in_bounds(self, min_point: "Point", max_point: "Point") -> None:
        coord = np.clip(self.coord, min_point.coord, max_point.coord)
        self._set_coord(coord)

class IntPoint(Point):
    def _set_coord(self, coord: np.ndarray) -> None:
        self._coord = np.rint(coord).astype(int)


RotationMatrixKey: TypeAlias = tuple[
    tuple[int, int, int],
    tuple[int, int, int],
    tuple[int, int, int],
]


@dataclass(frozen=True)
class SnappedRotation:
    rotation: Rotation | RotationMatrixKey

    def __post_init__(self) -> None:
        if isinstance(self.rotation, Rotation):
            rotation = self.rotation
        else:
            rotation = self._valide_rotation_from_key(self.rotation)
        
        object.__setattr__(self, "rotation", self._snap_rotation(rotation))

    @staticmethod
    def _valide_rotation_from_key(key: RotationMatrixKey) -> Rotation:
        matrix = np.asarray(key, dtype=int)

        if matrix.shape != (3, 3):
            raise ValueError(
                f"Rotation key must have shape (3, 3), got {matrix.shape}"
            )

        if not np.all(np.isin(matrix, (-1, 0, 1))):
            raise ValueError(
                "Rotation key entries must be -1, 0, or 1"
            )

        if not np.array_equal(
            matrix.T @ matrix,
            np.eye(3, dtype=int),
        ):
            raise ValueError(
                "Rotation key must be orthogonal"
            )

        if round(float(np.linalg.det(matrix))) != 1:
            raise ValueError(
                "Rotation key must have determinant +1"
            )

        return Rotation.from_matrix(matrix)

    @staticmethod
    def _snap_rotation(rotation: Rotation) -> Rotation:
        CARDINAL_ROTATIONS = Rotation.create_group("O")

        relative_rotations = CARDINAL_ROTATIONS.inv() * rotation
        angular_distances = relative_rotations.magnitude()

        closest_index = int(np.argmin(angular_distances))
        return CARDINAL_ROTATIONS[closest_index]

    @property
    def key(self) -> RotationMatrixKey:
        return tuple(tuple(map(int, row)) for row in np.rint(self.rotation.as_matrix()).astype(int))

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SnappedRotation) and self.key == other.key

    def __mul__(self, other: object) -> "SnappedRotation":
        if isinstance(other, SnappedRotation):
            combined = self.rotation * other.rotation
            return SnappedRotation(combined)

        if isinstance(other, Rotation):
            combined = self.rotation * other
            return SnappedRotation(combined)

        return NotImplemented

    @classmethod
    def identity(cls) -> "SnappedRotation":
        return cls(Rotation.identity())

    def inv(self) -> "SnappedRotation":
        return SnappedRotation(self.rotation.inv())

    def as_quat(self):
        return self.rotation.as_quat()


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
    def snapped_rotation_around_direction(self) -> SnappedRotation:
        rotations = {
            CardinalDirection.X: SnappedRotation(Rotation.from_euler("x", 90, degrees = True)),
            CardinalDirection.Y: SnappedRotation(Rotation.from_euler("y", 90, degrees = True)),
            CardinalDirection.Z: SnappedRotation(Rotation.from_euler("z", 90, degrees = True)),
            CardinalDirection.X_: SnappedRotation(Rotation.from_euler("x", -90, degrees = True)),
            CardinalDirection.Y_: SnappedRotation(Rotation.from_euler("y", -90, degrees = True)),
            CardinalDirection.Z_: SnappedRotation(Rotation.from_euler("z", -90, degrees = True)),
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
    

def _build_rotation_lookup() -> dict[SnappedRotation, list[CardinalDirection]]:
    lookup: dict[SnappedRotation, list[CardinalDirection]] = {SnappedRotation(Rotation.identity()): []}

    rotation_queue = deque([SnappedRotation.identity()])

    while len(lookup) < 24:
        rotation = rotation_queue.popleft()

        for direction in CardinalDirection:
            new_rotation = direction.snapped_rotation_around_direction * rotation

            if new_rotation not in lookup:
                lookup[new_rotation] = lookup[rotation] + [direction]
                rotation_queue.append(new_rotation)

    return lookup


ROTATION_LOOKUP = _build_rotation_lookup()


@dataclass(frozen=True)
class Orientation:
    forward: CardinalDirection
    up: CardinalDirection
    right: CardinalDirection = field(init=False)
    rotation: SnappedRotation = field(init=False)

    def __post_init__(self) -> None:
        if np.dot(self.forward.vec, self.up.vec) != 0:
            raise ValueError("forward and up must be perpendicular")
        
        object.__setattr__(self, "right", CardinalDirection(tuple(np.rint(np.cross(self.forward.vec, self.up.vec)).astype(int))))

        object.__setattr__(self, "rotation", SnappedRotation(Rotation.from_matrix(np.column_stack((self.right.vec, self.up.vec, -self.forward.vec)))))

    def rotate(self, snapped_rotation: SnappedRotation) -> "Orientation":
        return Orientation(self.forward.rotate(snapped_rotation.rotation), self.up.rotate(snapped_rotation.rotation))


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
    
    def rotate_data(self, rotation: SnappedRotation) -> np.ndarray:
        rotation_sequence = ROTATION_LOOKUP[rotation]

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

    def __post_init__(self) -> None:
        self.normalize_bounds()

    def move_min_point(self, direction: CardinalDirection, value: int, lower: int) -> None:
        self.min_point.move(direction, value)
        self.min_point.move_back_in_bounds_direction(direction, lower, self.max_point.coord[direction.dir])

    def move_max_point(self, direction: CardinalDirection, value: int, upper: int) -> None:
        self.max_point.move(direction, value)
        self.max_point.move_back_in_bounds_direction(direction, self.min_point.coord[direction.dir], upper)

    def move_min_point_to(self, direction: CardinalDirection, value: int, lower: int) -> None:
        self.min_point.move_to(direction, value)
        self.min_point.move_back_in_bounds_direction(direction, lower, self.max_point.coord[direction.dir])

    def move_max_point_to(self, direction: CardinalDirection, value: int, upper: int) -> None:
        self.max_point.move_to(direction, value)
        self.max_point.move_back_in_bounds_direction(direction, self.min_point.coord[direction.dir], upper)

    def normalize_bounds(self) -> None:
        self.min_point, self.max_point = (IntPoint(np.minimum(self.min_point.coord, self.max_point.coord)), IntPoint(np.maximum(self.min_point.coord, self.max_point.coord)))

    def rotate_about(self, rotation: Rotation, point: "Point | None" = None) -> "Domain":
        return Domain(self.min_point.rotate_about(rotation, point), self.max_point.rotate_about(rotation, point))

    def rotate_about_inplace(self, rotation: Rotation, point: "Point | None" = None) -> None:
        self.min_point.rotate_about_inplace(rotation, point)
        self.max_point.rotate_about_inplace(rotation, point)

        self.normalize_bounds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_point": self.min_point.coord.tolist(),
            "max_point": self.max_point.coord.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Domain | None":
        if "min_point" not in data or "max_point" not in data:
            return None
        
        return cls(IntPoint(np.array(data['min_point'])), IntPoint(np.array(data['max_point'])))

class GridType(str, Enum):
    NONE = "None"
    UNIDIR = "Unidir."
    BIDIR = "Bidir."

@dataclass
class SamplingDomain(Domain):
    # UnidirAuto, computes the voxel depth equal to the max X or Y dimension
    grid_type: GridType = GridType.NONE
    grid_divisions: np.typing.NDArray[np.int_] = field(default_factory=lambda: np.zeros(3, dtype=int))
    # doi_size = number divisions making up the doi, if Unidir doi_size[1] = Z voxel depth
    full_domain: bool = True
    uni_auto_depth: bool = True
    doi_size: np.typing.NDArray[np.int_] = field(default_factory=lambda: np.zeros(3, dtype=int))
    seed: int = 0


    @property
    def grid_spacing(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return tuple(np.linspace(min_coord, max_coord, divisions)
            for min_coord, max_coord, divisions in zip(self.min_point.coord, self.max_point.coord, self.grid_divisions + 2)
        )

    @property
    def doi(self) -> Domain:
        if self.full_domain or self.grid_type == GridType.NONE:
            return self

        grid_divisions = self.grid_divisions.copy()
        doi_size = self.doi_size.copy()
        grid_spacing = list(self.grid_spacing)

        if self.grid_type == GridType.UNIDIR:
            grid_divisions[2] = (self.max_point.coord[2] - self.min_point.coord[2] - 1)
            grid_spacing[2] = np.linspace(self.min_point.coord[2], self.max_point.coord[2], grid_divisions[2] + 2)

            if self.uni_auto_depth:
                x_spacing = grid_spacing[0]
                doi_size[2] = round(x_spacing[doi_size[0]] - x_spacing[0])

        rng = np.random.default_rng(self.seed)

        min_grid_point = rng.integers(0, np.maximum(0, grid_divisions - doi_size + 1), endpoint=True)
        max_grid_point = np.minimum(min_grid_point + doi_size, grid_divisions + 1)

        min_point = IntPoint(np.array([spacing[index] for spacing, index in zip(grid_spacing, min_grid_point)]))
        max_point = IntPoint(np.array([spacing[index] for spacing, index in zip(grid_spacing, max_grid_point)]))

        return Domain(min_point, max_point)

    def add_grid_divisions(self, direction: CardinalDirection, value: int) -> None:
        self.grid_divisions[direction.dir] += value

        np.maximum(self.grid_divisions, 0, out=self.grid_divisions)

    def set_grid_divisions(self, direction: CardinalDirection, value: int) -> None:
        self.grid_divisions[direction.dir] = value

        np.maximum(self.grid_divisions, 0, out=self.grid_divisions)

    def add_doi_size(self, direction: CardinalDirection, value: int) -> None:
        self.doi_size[direction.dir] += value

        np.maximum(self.doi_size, 1, out=self.doi_size)

    def set_doi_size(self, direction: CardinalDirection, value: int) -> None:
        self.doi_size[direction.dir] = value

        np.maximum(self.doi_size, 1, out=self.doi_size)

    def add_doi_seed(self, value: int) -> None:
        self.seed += value

        self.seed = max(self.seed, 0)

    def set_doi_seed(self, value: int) -> None:
        self.seed = value

        self.seed = max(self.seed, 0)

    def grid_lines_by_extremities(self) -> list[tuple[IntPoint, IntPoint]]:
        x_linespacing, y_linespacing, z_linespacing = self.grid_spacing

        def generate_lines(dir1_linespacing: np.ndarray, dir1 : CardinalDirection, dir2_linespacing: np.ndarray, dir2 : CardinalDirection) -> list[tuple[IntPoint, IntPoint]]:
            dir1_coords, dir2_coords = np.meshgrid(dir1_linespacing, dir2_linespacing)

            min_points = [IntPoint(np.put(coord := self.min_point.coord.astype(float), [dir1.dir, dir2.dir], [x, y]) or coord) for x, y in zip(dir1_coords.ravel(), dir2_coords.ravel())]
            max_points = [IntPoint(np.put(coord := self.max_point.coord.astype(float), [dir1.dir, dir2.dir], [x, y]) or coord) for x, y in zip(dir1_coords.ravel(), dir2_coords.ravel())]

            return list(zip(min_points, max_points))

        match self.grid_type:
            case GridType.NONE:
                return []

            case GridType.UNIDIR:
                return generate_lines(x_linespacing, CardinalDirection.X, y_linespacing, CardinalDirection.Y)
            
            case GridType.BIDIR:
                return generate_lines(x_linespacing, CardinalDirection.X, y_linespacing[::2], CardinalDirection.Y) + generate_lines(z_linespacing, CardinalDirection.Z, y_linespacing[1::2], CardinalDirection.Y)

            case _:
                raise ValueError(f"Unsupported sampling type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()

        data.update({
            "grid_type": self.grid_type.value,
            "grid_divisions": self.grid_divisions.tolist(),
            "full_domain": self.full_domain,
            "uni_auto_depth": self.uni_auto_depth,
            "doi_size": self.doi_size.tolist(),
            "seed": self.seed,
        })

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplingDomain | None":
        domain = Domain.from_dict(data)
        if domain is None:
            return None

        kwargs = {}

        if "grid_type" in data:
            kwargs["grid_type"] = GridType(data["grid_type"])

        if "grid_divisions" in data:
            kwargs["grid_divisions"] = np.array(data["grid_divisions"], dtype=int)

        if "full_domain" in data:
            kwargs["full_domain"] = data["full_domain"]

        if "uni_auto_depth" in data:
            kwargs["uni_auto_depth"] = data["uni_auto_depth"]

        if "doi_size" in data:
            kwargs["doi_size"] = np.array(data["doi_size"], dtype=int)

        if "seed" in data:
            kwargs["seed"] = data["seed"]

        return cls(
            min_point=domain.min_point,
            max_point=domain.max_point,
            **kwargs,
        )