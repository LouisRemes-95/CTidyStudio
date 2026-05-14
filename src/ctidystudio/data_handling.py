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
        if not coord.shape == (3,):
            raise ValueError("The coord give to a point should be a (3,) np.ndarray")
        
        self._coord = coord

    @property
    def coord(self):
        return self._coord
    
    @property
    def int_coord(self):
        return np.rint(self.coord).astype(int)
    
    def rotate(self, rotation: Rotation) -> "Point":
        return Point(rotation.apply(self.coord))
    
    def rotate_with_scan_center(self, rotation: Rotation, scan_center: "Point") -> "Point":
        return Point(rotation.apply(self.coord) + np.abs(rotation.apply(scan_center.coord)) - rotation.apply(scan_center.coord))
    
    def move(self, direction: "CardinalDirection", value: int) -> None:
        value = value if direction.vec[direction.dir] > 0 else -value

        self._coord[direction.dir] += value
    
    def move_to(self, direction: "CardinalDirection", value: int) -> None:
        value = value if direction.vec[direction.dir] > 0 else -value

        self._coord[direction.dir] = value

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
    def vec(self):
        return self._vec

    @property
    def dir(self):
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


# from pathlib import Path
# from enum import Enum
# from collections import deque
# from dataclasses import dataclass

# import tifffile
# import numpy as np
# from scipy.spatial.transform import Rotation as R
# from PySide6.QtCore import QRect, QPoint
# from PySide6.QtGui import QPixmap


# class Point:
#     def __init__(self, coord: np.ndarray):
#         if not coord.shape == (3,):
#             raise ValueError("The coord give to a point should be a (3,) np.ndarray")
        
#         self._coord = coord

#     @property
#     def coord(self):
#         return self._coord
    
#     def int_coord(self):
#         return np.rint(self.coord).astype(int)

#     def pixmap_coords(self, view_orientation: "Orientation", pixmap: QPixmap):
#         pass
    

# class CardinalDirection(Enum):
#     X  = (1, 0, 0)
#     Y  = (0, 1, 0)
#     Z  = (0, 0, 1)
#     X_ = (-1, 0, 0)
#     Y_ = (0, -1, 0)
#     Z_ = (0, 0, -1)

#     def __init__(self, x: int, y: int, z: int):
#         self._vec = np.array((x, y, z), dtype=int)
#         self._direction_index = np.nonzero(self._vec)[0][0]

#     @property
#     def vec(self):
#         return self._vec

#     @property
#     def dir(self):
#         return self._direction_index
    
#     @property
#     def rotation_around_direction(self) -> R:
#         rotations = {
#             CardinalDirection.X: R.from_euler("x", 90, degrees = True),
#             CardinalDirection.Y: R.from_euler("y", 90, degrees = True),
#             CardinalDirection.Z: R.from_euler("z", 90, degrees = True),
#             CardinalDirection.X_: R.from_euler("x", -90, degrees = True),
#             CardinalDirection.Y_: R.from_euler("y", -90, degrees = True),
#             CardinalDirection.Z_: R.from_euler("z", -90, degrees = True),
#         }
#         return rotations[self]

#     def __neg__(self) -> "CardinalDirection":
#         opposites = {
#             CardinalDirection.X: CardinalDirection.X_,
#             CardinalDirection.Y: CardinalDirection.Y_,
#             CardinalDirection.Z: CardinalDirection.Z_,
#             CardinalDirection.X_: CardinalDirection.X,
#             CardinalDirection.Y_: CardinalDirection.Y,
#             CardinalDirection.Z_: CardinalDirection.Z,
#         }
#         return opposites[self]
    
#     def rotating_plane(self) -> tuple[int, int]:
#         plane = {
#             CardinalDirection.X: (1, 2),
#             CardinalDirection.Y: (0, 2),
#             CardinalDirection.Z: (0, 1),
#             CardinalDirection.X_: (2, 1),
#             CardinalDirection.Y_: (2, 0),
#             CardinalDirection.Z_: (1, 0),
#         }
#         return plane[self]

#     def rotate(self, rotation: R) -> "CardinalDirection":
#         return CardinalDirection(tuple(np.rint(rotation.apply(self.vec)).astype(int)))


# @dataclass(frozen=True)
# class RotationKey:
#     rotation: R

#     def _key(self) -> tuple[float, float, float, float]:
#         q = self.rotation.as_quat()

#         if q[3] < 0:
#             q = -q

#         return tuple(round(float(x), 8) for x in q)

#     def __hash__(self) -> int:
#         return hash(self._key())

#     def __eq__(self, other: object) -> bool:
#         if not isinstance(other, RotationKey):
#             return False
#         return self._key() == other._key()


# def _build_rotation_lookup() -> dict[RotationKey, list[CardinalDirection]]:
#     lookup: dict[RotationKey, list[CardinalDirection]] = {RotationKey(R.identity()): []}

#     rotation_queue = deque([R.identity()])

#     while len(lookup) < 24:
#         rotation = rotation_queue.popleft()

#         for direction in CardinalDirection:
#             new_rotation = direction.rotation_around_direction * rotation
#             new_key = RotationKey(new_rotation)

#             if new_key not in lookup:
#                 lookup[new_key] = lookup[RotationKey(rotation)] + [direction]
#                 rotation_queue.append(new_rotation)

#     return lookup


# ROTATION_LOOKUP = _build_rotation_lookup()


# class Orientation:
#     def __init__(self, forward: CardinalDirection, up: CardinalDirection) -> None:
#         if np.dot(forward.vec, up.vec) != 0:
#             raise ValueError("forward and up must be perpendicular")
#         self.forward = forward
#         self.up = up

#     @property
#     def right(self) -> CardinalDirection:
#         return CardinalDirection(tuple(np.cross(self.forward.vec, self.up.vec)))
    
#     def copy(self) -> "Orientation":
#         return Orientation(self.forward, self.up)
    
#     def rotate(self, rotation: R) -> None:
#         self.forward = self.forward.rotate(rotation)
#         self.up = self.up.rotate(rotation)


# class Scan:
#     def __init__(self, voxel_size: float, data: np.ndarray) -> None:
#         if voxel_size <= 0:
#             raise ValueError("voxel size must be positive")
#         self.voxel_size = voxel_size

#         if not isinstance(data, np.ndarray):
#             raise TypeError("data must be a numpy ndarray")
#         if data.ndim != 3:
#             raise ValueError(f"data must be 3D (z, y, x), got {data.ndim}D")
#         self.data = data
#         self.compute_center()

#     @property
#     def shape(self):
#         return self.data.shape

#     def quantization_to_uint8(self) -> None:
#         data = self.data
#         data_min = data.min()
#         data_max = data.max()

#         if data_max == data_min:
#             self.data = np.zeros(data.shape, dtype=np.uint8)
#             return

#         self.data = ((data - data_min) / (data_max - data_min) * 255).astype(np.uint8)

#     def rot90(self, rotation_axis: CardinalDirection) -> None:
#         self.data = np.rot90(self.data, 1, rotation_axis.rotating_plane())
#         self.compute_center()

#     def compute_center(self):
#         self.center = Point((np.array(self.data.shape)-1)/2)


# class DomainOfInterest:
#     def __init__(self, shape: tuple[int, int, int]) -> None:
#         self.origin = Point(np.array([0, 0, 0]))
#         self.opposit_point = Point(np.array([shape[0]-1, shape[1]-1, shape[2]-1]))

#     def view_box(self, orientation: Orientation, pixmap_height: int) -> QRect:
#         origin_pixmap_coord = view_to_pixmap_coord(self.origin, orientation, pixmap_height)
#         opposit_pixmap_coord = view_to_pixmap_coord(self.opposit_point, orientation, pixmap_height)

#         if origin_pixmap_coord.x() > opposit_pixmap_coord.x():
#             min_x = opposit_pixmap_coord.x()
#             opposit_pixmap_coord.setX(origin_pixmap_coord.x())
#             origin_pixmap_coord.setX(min_x)

#         if origin_pixmap_coord.y() > opposit_pixmap_coord.y():
#             min_x = opposit_pixmap_coord.y()
#             opposit_pixmap_coord.setY(origin_pixmap_coord.y())
#             origin_pixmap_coord.setY(min_x)

#         return QRect(origin_pixmap_coord, opposit_pixmap_coord)
    
#     def move_origin(self, direction: CardinalDirection, increment: int):
#         self.origin += direction.vec * increment

#     def set_origin_component(self, direction: CardinalDirection, value: int):
#         self.origin[direction.dir] = value
    
#     def origin_coord_in_direction(self, direction: CardinalDirection) -> int:
#         return int(self.origin[direction.dir])
    

# def rotate_and_translate_point(point: np.ndarray, direction: CardinalDirection, source_pivot: np.ndarray, target_pivot: np.ndarray) -> np.ndarray:
#     if point.shape != (3,) or source_pivot.shape != (3,) or target_pivot.shape != (3,):
#         raise ValueError("point, source_pivot, and target_pivot must all have shape (3,)")

#     rotation = R.from_euler(**direction.rotation_around_direction())

#     return (rotation.apply((point - source_pivot)) + target_pivot)


# def view_to_pixmap_coord(point: np.ndarray, orientation: Orientation, pixmap_height: int) -> QPoint:
#     return QPoint(np.dot(orientation.right.vec, point), pixmap_height - 1 - np.dot(orientation.up.vec, point))


# def pixmap_to_view_coord(point: QPoint, orientation: Orientation, pixmap_height: int, slice_index: int) -> np.ndarray:
#     return point.x() * orientation.right.vec + (pixmap_height - point.y()) * orientation.up.vec + slice_index * orientation.forward.vec



