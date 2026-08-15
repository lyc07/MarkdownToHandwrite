from __future__ import annotations

import io
import math
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


BUNDLED_TRAJECTORIES = Path(__file__).resolve().parent / "assets" / "sdt_trajectories.zip"


@dataclass(frozen=True)
class TrajectoryStyle:
    rotation_sigma_deg: float = 0.45
    coordinate_jitter: float = 0.6
    jitter_correlation: float = 10.0
    width_jitter: float = 0.10
    taper: float = 0.22
    supersample: int = 3


class SdtTrajectoryStore:
    """Read SDT ``coords/*.npy`` data from a directory or a compact zip asset."""

    def __init__(self, source: str | Path | None = None, project_root: Path | None = None):
        self.path = _resolve_source(source, project_root)
        self._archive: zipfile.ZipFile | None = None
        self._names: set[str] = set()
        if self.path is None:
            return
        if self.path.is_file() and self.path.suffix.lower() == ".zip":
            self._archive = zipfile.ZipFile(self.path)
            self._names = set(self._archive.namelist())

    @property
    def available(self) -> bool:
        return self.path is not None

    def contains(self, char: str) -> bool:
        if not self.available or len(char) != 1:
            return False
        name = f"{ord(char):04x}.npy"
        if self._archive is not None:
            return name in self._names or f"coords/{name}" in self._names
        return self._coordinate_path(name).is_file()

    @lru_cache(maxsize=2048)
    def load(self, char: str) -> tuple[np.ndarray, ...] | None:
        if not self.contains(char):
            return None
        name = f"{ord(char):04x}.npy"
        if self._archive is not None:
            archive_name = name if name in self._names else f"coords/{name}"
            with self._archive.open(archive_name) as source:
                coordinates = np.load(io.BytesIO(source.read()), allow_pickle=False)
        else:
            coordinates = np.load(self._coordinate_path(name), allow_pickle=False)
        return coordinates_to_strokes(coordinates)

    def _coordinate_path(self, name: str) -> Path:
        assert self.path is not None
        coords = self.path / "coords"
        return (coords if coords.is_dir() else self.path) / name


def _resolve_source(source: str | Path | None, project_root: Path | None) -> Path | None:
    if source:
        candidate = Path(source).expanduser()
        candidates = [candidate]
        if not candidate.is_absolute() and project_root is not None:
            candidates.insert(0, project_root / candidate)
        for item in candidates:
            if item.is_file() or item.is_dir():
                return item.resolve()
        return None
    return BUNDLED_TRAJECTORIES if BUNDLED_TRAJECTORIES.is_file() else None


def coordinates_to_strokes(coordinates: np.ndarray) -> tuple[np.ndarray, ...]:
    """Convert SDT relative x/y and pen-state columns into absolute polylines."""
    values = np.asarray(coordinates, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] < 4 or len(values) == 0:
        raise ValueError("Invalid SDT trajectory array.")
    values = values.copy()
    values[:, :2] = np.cumsum(values[:, :2], axis=0)
    if values.shape[1] >= 5:
        endings = np.flatnonzero(values[:, 4] == 1)
        if len(endings):
            values = values[: endings[0]]
    if len(values) == 0:
        return ()
    breaks = np.flatnonzero(values[:, 3] == 1) + 1
    strokes = np.split(values[:, :2], breaks)
    return tuple(stroke.copy() for stroke in strokes if len(stroke))


def render_strokes(
    strokes: tuple[np.ndarray, ...],
    width: int,
    height: int,
    stroke_width: float,
    ink: tuple[int, ...],
    rng: np.random.Generator,
    style: TrajectoryStyle,
    em_size: int | None = None,
) -> Image.Image:
    """Render vector strokes with smooth, reproducible position and pressure noise."""
    width = max(1, int(width))
    height = max(1, int(height))
    if not strokes:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))
    child_seeds = rng.integers(0, np.iinfo(np.int64).max, size=2, dtype=np.int64)
    geometry_rng = np.random.default_rng(int(child_seeds[0]))
    ink_rng = np.random.default_rng(int(child_seeds[1]))
    supersample = max(1, int(style.supersample))
    em_size = max(1, int(em_size if em_size is not None else min(width, height)))
    sample_spacing = max(0.5, em_size / 80.0)
    fitted = tuple(
        _resample_stroke(stroke, sample_spacing)
        for stroke in _fit_strokes(strokes, width, height, padding_ratio=0.045)
    )
    center = np.array([width / 2.0, height / 2.0], dtype=np.float32)
    angle = math.radians(float(geometry_rng.normal(0.0, max(0.0, style.rotation_sigma_deg))))
    rotation = np.array(
        [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]],
        dtype=np.float32,
    )
    jitter_scale = em_size / 256.0
    varied_strokes: list[np.ndarray] = []
    varied_widths: list[np.ndarray] = []
    for stroke in fitted:
        xy = (stroke - center) @ rotation.T + center
        xy += _smooth_noise(
            geometry_rng,
            len(stroke),
            max(0.0, style.coordinate_jitter) * jitter_scale,
            max(1.0, style.jitter_correlation),
            dimensions=2,
        )
        pressure = 1.0 + _smooth_noise(
            ink_rng,
            len(stroke),
            max(0.0, style.width_jitter),
            max(1.0, style.jitter_correlation),
        )
        pressure *= float(np.clip(ink_rng.normal(1.0, style.width_jitter * 0.45), 0.82, 1.18))
        if len(stroke) >= 4 and style.taper > 0:
            edge = max(2, min(len(stroke) // 3, math.ceil(len(stroke) * 0.16)))
            ramp = np.linspace(1.0 - min(0.8, style.taper), 1.0, edge)
            pressure[:edge] *= ramp
            pressure[-edge:] *= ramp[::-1]
        varied_strokes.append(xy)
        varied_widths.append(max(0.35, stroke_width) * np.clip(pressure, 0.62, 1.38))

    mask = Image.new("L", (width * supersample, height * supersample), 0)
    draw = ImageDraw.Draw(mask)
    for stroke, widths in zip(varied_strokes, varied_widths):
        points = stroke * supersample
        pen_widths = np.maximum(1, np.rint(widths * supersample).astype(int))
        if len(points) == 1:
            _draw_disc(draw, points[0], pen_widths[0])
            continue
        for index in range(len(points) - 1):
            segment_width = max(1, round((pen_widths[index] + pen_widths[index + 1]) / 2))
            p0 = tuple(points[index])
            p1 = tuple(points[index + 1])
            draw.line((p0, p1), fill=255, width=segment_width)
            _draw_disc(draw, points[index], segment_width)
        _draw_disc(draw, points[-1], pen_widths[-1])
    if supersample > 1:
        mask = mask.resize((width, height), Image.Resampling.LANCZOS)
    result = Image.new("RGBA", (width, height), ink)
    result.putalpha(mask)
    return result


def _draw_disc(draw: ImageDraw.ImageDraw, point: np.ndarray, width: int) -> None:
    radius = max(1, width) / 2.0
    x, y = point
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)


def _fit_strokes(
    strokes: tuple[np.ndarray, ...],
    width: int,
    height: int,
    padding_ratio: float,
) -> tuple[np.ndarray, ...]:
    points = np.concatenate(strokes, axis=0)
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    extent = np.maximum(maximum - minimum, 1e-4)
    pad_x = max(0.5, width * padding_ratio)
    pad_y = max(0.5, height * padding_ratio)
    scale = min(max(1.0, width - 2 * pad_x) / extent[0], max(1.0, height - 2 * pad_y) / extent[1])
    used = extent * scale
    offset = np.array([(width - used[0]) / 2.0, (height - used[1]) / 2.0], dtype=np.float32)
    return tuple((stroke - minimum) * scale + offset for stroke in strokes)


def _resample_stroke(stroke: np.ndarray, spacing: float) -> np.ndarray:
    """Normalize point density so noise parameters behave alike for every source."""
    points = np.asarray(stroke, dtype=np.float32)
    if len(points) <= 1:
        return points.copy()
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    keep = np.concatenate(([True], segment_lengths > 1e-5))
    points = points[keep]
    if len(points) <= 1:
        return points.copy()
    distances = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))))
    total = float(distances[-1])
    if total <= 1e-5:
        return points[:1].copy()
    samples = np.arange(0.0, total, max(0.1, spacing), dtype=np.float32)
    if len(samples) == 0 or samples[-1] < total:
        samples = np.append(samples, total)
    return np.stack(
        (
            np.interp(samples, distances, points[:, 0]),
            np.interp(samples, distances, points[:, 1]),
        ),
        axis=1,
    ).astype(np.float32)


def _smooth_noise(
    rng: np.random.Generator,
    count: int,
    sigma: float,
    correlation: float,
    dimensions: int = 1,
) -> np.ndarray:
    if count <= 0 or sigma <= 0:
        shape = (count, dimensions) if dimensions > 1 else (count,)
        return np.zeros(shape, dtype=np.float32)
    knot_count = max(3, math.ceil(max(count - 1, 1) / correlation) + 1)
    knot_x = np.linspace(0, max(count - 1, 1), knot_count)
    sample_x = np.arange(count)
    values = rng.normal(0.0, sigma, size=(knot_count, dimensions))
    result = np.stack(
        [np.interp(sample_x, knot_x, values[:, axis]) for axis in range(dimensions)],
        axis=1,
    )
    return result if dimensions > 1 else result[:, 0]


@lru_cache(maxsize=1024)
def font_glyph_strokes(font_path: str, char: str) -> tuple[np.ndarray, ...]:
    """Derive centerline trajectories for symbols absent from the SDT charset."""
    if not char or char.isspace():
        return ()
    font = ImageFont.truetype(font_path, 192)
    bbox = font.getbbox(char)
    if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return ()
    pad = 8
    mask = Image.new("L", (bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad), 0)
    draw = ImageDraw.Draw(mask)
    draw.text((pad - bbox[0], pad - bbox[1]), char, fill=255, font=font)
    skeleton = _zhang_suen(np.asarray(mask) >= 64)
    return _trace_skeleton(skeleton)


def _zhang_suen(source: np.ndarray) -> np.ndarray:
    image = np.pad(source.astype(np.uint8), 1)
    for _ in range(96):
        changed = False
        for first_pass in (True, False):
            center = image[1:-1, 1:-1]
            p2 = image[:-2, 1:-1]
            p3 = image[:-2, 2:]
            p4 = image[1:-1, 2:]
            p5 = image[2:, 2:]
            p6 = image[2:, 1:-1]
            p7 = image[2:, :-2]
            p8 = image[1:-1, :-2]
            p9 = image[:-2, :-2]
            neighbors = (p2, p3, p4, p5, p6, p7, p8, p9)
            count = sum(neighbors)
            transitions = sum((left == 0) & (right == 1) for left, right in zip(neighbors, (*neighbors[1:], neighbors[0])))
            removable = (center == 1) & (count >= 2) & (count <= 6) & (transitions == 1)
            if first_pass:
                removable &= (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                removable &= (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            if np.any(removable):
                center[removable] = 0
                changed = True
        if not changed:
            break
    return image[1:-1, 1:-1].astype(bool)


def _trace_skeleton(skeleton: np.ndarray) -> tuple[np.ndarray, ...]:
    pixels = {tuple(point) for point in np.argwhere(skeleton)}
    if not pixels:
        return ()

    def neighbors(point: tuple[int, int]) -> list[tuple[int, int]]:
        y, x = point
        return [
            (y + dy, x + dx)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (dy or dx) and (y + dy, x + dx) in pixels
        ]

    adjacency = {point: neighbors(point) for point in pixels}
    used: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    paths: list[np.ndarray] = []

    def edge(a: tuple[int, int], b: tuple[int, int]):
        return (a, b) if a <= b else (b, a)

    def walk(start: tuple[int, int], following: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, following]
        used.add(edge(start, following))
        previous, current = start, following
        while len(adjacency[current]) == 2:
            choices = [item for item in adjacency[current] if item != previous]
            if not choices or edge(current, choices[0]) in used:
                break
            following = choices[0]
            used.add(edge(current, following))
            path.append(following)
            previous, current = current, following
        return path

    starts = sorted(point for point, items in adjacency.items() if len(items) != 2)
    for start in starts:
        if not adjacency[start]:
            paths.append(np.array([[start[1], start[0]]], dtype=np.float32))
        for following in adjacency[start]:
            if edge(start, following) not in used:
                points = walk(start, following)
                paths.append(_simplify_path(points))
    for start, items in adjacency.items():
        for following in items:
            if edge(start, following) not in used:
                paths.append(_simplify_path(walk(start, following)))
    return tuple(path for path in paths if len(path))


def _simplify_path(points: list[tuple[int, int]]) -> np.ndarray:
    xy = np.array([(x, y) for y, x in points], dtype=np.float32)
    if len(xy) <= 2:
        return xy
    return _rdp(xy, tolerance=1.15)


def _rdp(points: np.ndarray, tolerance: float) -> np.ndarray:
    if len(points) <= 2:
        return points
    start, end = points[0], points[-1]
    segment = end - start
    length = float(np.linalg.norm(segment))
    if length <= 1e-6:
        distances = np.linalg.norm(points - start, axis=1)
    else:
        offsets = points - start
        distances = np.abs(segment[0] * offsets[:, 1] - segment[1] * offsets[:, 0]) / length
    index = int(np.argmax(distances))
    if distances[index] <= tolerance:
        return np.stack((start, end))
    return np.concatenate((_rdp(points[: index + 1], tolerance)[:-1], _rdp(points[index:], tolerance)))
