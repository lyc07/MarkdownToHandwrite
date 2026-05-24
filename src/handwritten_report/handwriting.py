from __future__ import annotations

import hashlib
import random
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import HandwritingConfig, color

try:
    from handright import Template, handwrite
except Exception:  # pragma: no cover - dependency fallback
    Template = None
    handwrite = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
DEFAULT_SYSTEM_FONT_CANDIDATES = (
    "C:/Windows/Fonts/simkai.ttf",
    "C:/Windows/Fonts/STKAITI.TTF",
    "C:/Windows/Fonts/simfang.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
)
GLYPH_VERTICAL_ADJUSTMENTS = {
    "一": 0.42,
}


class HandwritingEngine:
    def __init__(self, config: HandwritingConfig):
        self.config = config
        self.font_paths = _resolve_font_chain(config.font_path, config.fallback_font_path)
        self.font_path = self.font_paths[0]
        self.math_font_paths = (
            _resolve_font_chain(config.math_font_path, config.fallback_font_path)
            if config.math_font_path
            else self.font_paths
        )
        self.math_font_path = self.math_font_paths[0]
        self.fallback_font_path = self.font_paths[min(1, len(self.font_paths) - 1)]
        self.ink = color(config.ink_color, 255)
        self.handright_available = bool(config.prefer_handright and Template is not None and handwrite is not None)

    def font(self, size_px: int, math: bool = False, fallback: bool = False) -> ImageFont.FreeTypeFont:
        paths = self.math_font_paths if math else self.font_paths
        index = min(1, len(paths) - 1) if fallback else 0
        return _load_font(paths[index], size_px)

    def measure(self, text: str, size_px: int, math: bool = False) -> float:
        return sum(
            _measure_text(_load_font(font_path, size_px), char)
            for font_path, char in self._font_runs(text, size_px, math=math)
        )

    def render_line(self, text: str, size_px: int, max_width: int, seed_extra: str = "", math: bool = False) -> Image.Image:
        text = text.rstrip()
        if not text:
            return Image.new("RGBA", (1, max(1, round(size_px * self.config.line_spacing))), (0, 0, 0, 0))
        seed = _stable_seed(self.config.seed, text, size_px, max_width, seed_extra)
        if self.handright_available:
            try:
                return self._render_with_handright(text, size_px, max_width, seed, math=math)
            except Exception:
                pass
        return self._render_with_pillow(text, size_px, max_width, seed, math=math)

    def _render_with_handright(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False) -> Image.Image:
        pad_x = max(8, round(size_px * 0.35))
        pad_y = max(8, round(size_px * 0.35))
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        max_shift = max(
            self._baseline_shift(font_path, size_px, reference_ascent) + self._run_vertical_adjustment(run, size_px)
            for font_path, run in runs
        )
        run_height = max(size_px + 2 * pad_y, round(size_px * self.config.line_spacing))
        line_height = run_height + 2 * pad_y + max_shift
        width = max(16, min(max_width + 2 * pad_x, round(self.measure(text, size_px, math=math) + 3 * pad_x)))
        background = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = pad_x
        for index, (font_path, run) in enumerate(runs):
            run_image = self._render_handright_run(run, size_px, max_width, _stable_seed(seed, index), font_path)
            y = (
                pad_y
                + self._baseline_shift(font_path, size_px, reference_ascent)
                + self._run_vertical_adjustment(run, size_px)
            )
            background.alpha_composite(run_image, (round(x), y))
            x += _measure_text(_load_font(font_path, size_px), run)
        return _crop_alpha(background, pad=4)

    def _render_handright_run(self, text: str, size_px: int, max_width: int, seed: int, font_path: str) -> Image.Image:
        font = _load_font(font_path, size_px)
        pad_x = max(8, round(size_px * 0.35))
        pad_y = max(8, round(size_px * 0.35))
        line_height = max(size_px + 2 * pad_y, round(size_px * self.config.line_spacing))
        width = max(16, min(max_width + 2 * pad_x, round(_measure_text(font, text) + 2.8 * pad_x)))
        background = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        template = Template(
            background=background,
            font=font,
            line_spacing=line_height,
            fill=self.ink,
            left_margin=pad_x,
            top_margin=pad_y,
            right_margin=pad_x,
            bottom_margin=0,
            word_spacing=self.config.word_spacing_px,
            perturb_x_sigma=self.config.perturb_x_sigma_px,
            perturb_y_sigma=self.config.perturb_y_sigma_px,
            perturb_theta_sigma=self.config.perturb_theta_sigma,
        )
        image = next(iter(handwrite(text, template, seed=seed))).convert("RGBA")
        return image

    def _render_with_pillow(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False) -> Image.Image:
        rand = random.Random(seed)
        pad = max(8, round(size_px * 0.4))
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        descent = max(_load_font(font_path, size_px).getmetrics()[1] for font_path, _ in runs)
        max_adjustment = max(self._glyph_vertical_adjustment(char, size_px) for char in text)
        line_height = max(round(size_px * self.config.line_spacing), reference_ascent + descent + 2 * pad + max_adjustment)
        width = max(16, min(max_width + 2 * pad, round(self.measure(text, size_px, math=math) + 2 * pad)))
        image = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = pad
        baseline = pad + reference_ascent
        for char in text:
            font_path = self._font_path_for_char(char, size_px, math=math)
            font = _load_font(font_path, size_px)
            if char == " ":
                x += max(size_px * 0.35, _measure_text(font, " "))
                continue
            bbox = font.getbbox(char)
            char_w = max(1, round(_measure_text(font, char)))
            glyph = Image.new("RGBA", (char_w + 2 * pad, line_height), (0, 0, 0, 0))
            glyph_draw = ImageDraw.Draw(glyph)
            glyph_y = baseline - font.getmetrics()[0] + self._glyph_vertical_adjustment(char, size_px)
            glyph_draw.text((pad - bbox[0], glyph_y), char, fill=self.ink, font=font)
            angle = rand.gauss(0, self.config.perturb_theta_sigma * 35)
            glyph = glyph.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
            image.alpha_composite(glyph, (round(x - pad + rand.gauss(0, 1.2)), round(rand.gauss(0, 1.2))))
            x += char_w + self.config.word_spacing_px + rand.gauss(0, 0.8)
        return _crop_alpha(image, pad=4)

    def _font_runs(self, text: str, size_px: int, math: bool = False) -> list[tuple[str, str]]:
        runs: list[tuple[str, str]] = []
        for char in text:
            font_path = self._font_path_for_char(char, size_px, math=math)
            if (
                runs
                and runs[-1][0] == font_path
                and self._run_vertical_adjustment(runs[-1][1], size_px) == self._glyph_vertical_adjustment(char, size_px)
            ):
                runs[-1] = (font_path, runs[-1][1] + char)
            else:
                runs.append((font_path, char))
        return runs

    def _font_path_for_char(self, char: str, size_px: int, math: bool = False) -> str:
        paths = self.math_font_paths if math else self.font_paths
        if char.isspace():
            return paths[0]
        for font_path in paths:
            if _has_glyph(font_path, size_px, char):
                return font_path
        return paths[-1]

    def _reference_ascent(self, runs: list[tuple[str, str]], size_px: int) -> int:
        return max(_load_font(font_path, size_px).getmetrics()[0] for font_path, _ in runs)

    def _baseline_shift(self, font_path: str, size_px: int, reference_ascent: int) -> int:
        ascent = _load_font(font_path, size_px).getmetrics()[0]
        return max(0, reference_ascent - ascent)

    def _glyph_vertical_adjustment(self, char: str, size_px: int) -> int:
        return round(size_px * GLYPH_VERTICAL_ADJUSTMENTS.get(char, 0.0))

    def _run_vertical_adjustment(self, run: str, size_px: int) -> int:
        return self._glyph_vertical_adjustment(run[0], size_px) if run else 0


def wrap_text(engine: HandwritingEngine, text: str, size_px: int, max_width: int, math: bool = False) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines() or [""]:
        units = _wrap_units(raw_line)
        current = ""
        for unit in units:
            candidate = (current + unit).strip() if not current else current + unit
            if current and engine.measure(candidate, size_px, math=math) > max_width:
                lines.append(current.strip())
                current = unit.strip()
            else:
                current = candidate
        if current.strip():
            lines.append(current.strip())
        elif not units:
            lines.append("")
    return lines


def _wrap_units(text: str) -> list[str]:
    units: list[str] = []
    buffer = ""
    for char in text:
        if char.isspace():
            if buffer:
                units.append(buffer)
                buffer = ""
            units.append(" ")
        elif ord(char) < 128 and (char.isalnum() or char in "._-/^=+"):
            buffer += char
        else:
            if buffer:
                units.append(buffer)
                buffer = ""
            units.append(char)
    if buffer:
        units.append(buffer)
    return units


@lru_cache(maxsize=128)
def _load_font(font_path: str, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(font_path, size_px)


def _resolve_font(preferred: str | None) -> str:
    return _resolve_font_chain(preferred)[0]


def _resolve_font_chain(preferred: str | None, fallback: str | None = None) -> list[str]:
    paths: list[str] = []

    def add(candidate: Path) -> None:
        resolved = str(candidate.resolve())
        if candidate.is_file() and resolved not in paths:
            paths.append(resolved)

    if preferred:
        for candidate in _preferred_font_candidates(preferred):
            if candidate.is_file():
                add(candidate)
                break

    local_fonts = _local_font_candidates()
    if not paths and local_fonts:
        add(local_fonts[0])

    if fallback:
        for candidate in _preferred_font_candidates(fallback):
            if candidate.is_file():
                add(candidate)
                break

    for candidate in local_fonts:
        add(candidate)
    for candidate in DEFAULT_SYSTEM_FONT_CANDIDATES:
        add(Path(candidate))

    if paths:
        return paths
    raise FileNotFoundError(
        "No usable handwriting font found. Add numbered font files such as font/1.ttf and font/2.ttf, "
        "or set handwriting.font_path in config."
    )


def _preferred_font_candidates(preferred: str) -> list[Path]:
    path = Path(preferred)
    if path.is_absolute():
        return [path]
    return [Path.cwd() / path, PROJECT_ROOT / path]


def _local_font_candidates() -> list[Path]:
    directories = [Path.cwd() / "font", PROJECT_ROOT / "font"]
    candidates: list[Path] = []
    seen: set[Path] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.iterdir(), key=_font_order_key):
            resolved = candidate.resolve()
            if candidate.is_file() and candidate.suffix.lower() in FONT_EXTENSIONS and resolved not in seen:
                candidates.append(candidate)
                seen.add(resolved)
    return candidates


def _font_order_key(path: Path) -> tuple:
    if path.stem.isdigit():
        return (0, int(path.stem), path.suffix.casefold())
    pieces = tuple(
        (0, int(piece)) if piece.isdigit() else (1, piece.casefold())
        for piece in re.split(r"(\d+)", path.name)
        if piece
    )
    return (1, pieces)


def _measure_text(font: ImageFont.FreeTypeFont, text: str) -> float:
    if not text:
        return 0.0
    scratch = Image.new("L", (1, 1), 0)
    draw = ImageDraw.Draw(scratch)
    return draw.textlength(text, font=font)


@lru_cache(maxsize=4096)
def _has_glyph(font_path: str, size_px: int, char: str) -> bool:
    font = _load_font(font_path, size_px)
    missing = "\u0378"
    return (font.getbbox(char), bytes(font.getmask(char))) != (
        font.getbbox(missing),
        bytes(font.getmask(missing)),
    )


def _crop_alpha(image: Image.Image, pad: int = 0) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, image.height), (0, 0, 0, 0))
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(image.width, bbox[2] + pad)
    bottom = min(image.height, bbox[3] + pad)
    return image.crop((left, top, right, bottom))


def _stable_seed(*parts: object) -> int:
    joined = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)
