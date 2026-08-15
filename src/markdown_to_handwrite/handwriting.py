from __future__ import annotations

import hashlib
import math
import random
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import HandwritingConfig, color
from .sdt_renderer import SdtTrajectoryStore, TrajectoryStyle, font_glyph_strokes, render_strokes

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
GLYPH_VERTICAL_ADJUSTMENTS: dict[str, float] = {}
FORBIDDEN_LINE_START_PUNCTUATION = frozenset(",.;:!?%)]}>\"'")
DEFAULT_RENDER_DPI = 180.0
TEXT_STROKE_WEIGHT_SAMPLE = "永重力加速度ABC123"
MATH_STROKE_WEIGHT_SAMPLE = "xTgabcmn0123456789+-=()[]"
MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX = 1.0
MAX_STROKE_WEIGHT_ADJUSTMENT_PX = 2.0


class HandwritingEngine:
    def __init__(
        self,
        config: HandwritingConfig,
        reference_size_px: int | None = None,
        math_reference_size_px: int | None = None,
    ):
        self.config = config
        self.reference_size_px = max(
            1,
            reference_size_px
            if reference_size_px is not None
            else round(config.body_font_pt / 72.0 * DEFAULT_RENDER_DPI),
        )
        self.math_reference_size_px = max(
            1,
            math_reference_size_px
            if math_reference_size_px is not None
            else round(config.math_font_pt / 72.0 * DEFAULT_RENDER_DPI),
        )
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
        self.trajectory_store = SdtTrajectoryStore(config.sdt_trajectory_path, PROJECT_ROOT)
        self.uses_sdt_trajectories = bool(config.sdt_trajectory_enabled and self.trajectory_store.available)
        self.handright_available = bool(config.prefer_handright and Template is not None and handwrite is not None)
        self.reference_stroke_weight = _font_optical_weight(
            self.font_path,
            self.reference_size_px,
            TEXT_STROKE_WEIGHT_SAMPLE,
        )
        self.math_reference_stroke_weight = _font_optical_weight(
            self.math_font_path,
            self.math_reference_size_px,
            MATH_STROKE_WEIGHT_SAMPLE,
        )

    def font(self, size_px: int, math: bool = False, fallback: bool = False) -> ImageFont.FreeTypeFont:
        paths = self.math_font_paths if math else self.font_paths
        index = min(1, len(paths) - 1) if fallback else 0
        return _load_font(paths[index], size_px)

    def measure(self, text: str, size_px: int, math: bool = False) -> float:
        return sum(
            _measure_text(_load_font(font_path, size_px), char)
            for font_path, char in self._font_runs(text, size_px, math=math)
        )

    def render_line(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed_extra: str = "",
        math: bool = False,
        weight_seed_extra: str | None = None,
        return_baseline: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        text = text.rstrip()
        if not text:
            image = Image.new("RGBA", (1, max(1, round(size_px * self.config.line_spacing))), (0, 0, 0, 0))
            baseline = max(1, round(size_px * 0.75))
            return (image, baseline) if return_baseline else image
        seed = _stable_seed(self.config.seed, text, size_px, max_width, seed_extra)
        if self.uses_sdt_trajectories:
            image, baseline = self._render_with_trajectories(
                text,
                size_px,
                max_width,
                seed,
                math=math,
                return_baseline=True,
            )
        elif self.handright_available:
            try:
                image = self._render_with_handright(text, size_px, max_width, seed, math=math)
            except Exception:
                image = self._render_with_pillow(text, size_px, max_width, seed, math=math)
            baseline = self._estimated_rendered_baseline(text, size_px, image, math=math)
        else:
            image = self._render_with_pillow(text, size_px, max_width, seed, math=math)
            baseline = self._estimated_rendered_baseline(text, size_px, image, math=math)
        image, baseline = self._apply_second_layer(
            image,
            size_px,
            _stable_seed(seed, "second-layer"),
            math_mode=math,
            reference_weight=self._reference_weight_for_text(text, size_px, math_mode=math),
            weight_seed=(
                _stable_seed(self.config.seed, "stroke-weight", weight_seed_extra)
                if weight_seed_extra is not None
                else None
            ),
            normalize_weight=not self.uses_sdt_trajectories,
            baseline_px=baseline,
            return_baseline=True,
        )
        return (image, baseline) if return_baseline else image

    def _apply_second_layer(
        self,
        image: Image.Image,
        size_px: int,
        seed: int,
        math_mode: bool = False,
        reference_weight: float | None = None,
        weight_seed: int | None = None,
        normalize_weight: bool = True,
        baseline_px: int | None = None,
        return_baseline: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        """Perturb the rasterized ink mask after the character-level rendering pass."""
        if not self.config.second_layer_enabled or image.getchannel("A").getbbox() is None:
            baseline = baseline_px if baseline_px is not None else max(1, round(image.height * 0.76))
            return (image, baseline) if return_baseline else image

        geometry_rand = random.Random(_stable_seed(seed, "geometry"))
        ink_rand = random.Random(_stable_seed(seed, "ink"))
        elastic_strength = max(0.0, size_px * self.config.elastic_strength_ratio)
        baseline_amplitude = max(0.0, size_px * self.config.baseline_wave_amplitude_ratio)
        random_weight_sigma = self._random_stroke_weight_sigma(math_mode=math_mode)
        pad = max(
            4,
            math.ceil(
                elastic_strength * 3
                + baseline_amplitude
                + MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX
                + 3 * random_weight_sigma
                + 2
            ),
        )
        padded = Image.new("RGBA", (image.width + 2 * pad, image.height + 2 * pad), (0, 0, 0, 0))
        padded.alpha_composite(image, (pad, pad))
        alpha = padded.getchannel("A")

        # Geometric resampling changes the apparent weight most strongly for
        # small math glyphs, so normalize only after the warp has completed.
        alpha = _warp_ink_mask(
            alpha,
            geometry_rand,
            elastic_strength=elastic_strength,
            elastic_smoothness=max(2.0, size_px * self.config.elastic_smoothness_ratio),
            baseline_amplitude=baseline_amplitude,
            baseline_wavelength=max(2.0, size_px * self.config.baseline_wave_length_em),
        )
        base_weight_adjustment = (
            self._base_stroke_weight_adjustment(
                alpha,
                math_mode=math_mode,
                reference_weight=reference_weight,
            )
            if normalize_weight
            else 0.0
        )
        weight_rand = random.Random(
            weight_seed if weight_seed is not None else _stable_seed(seed, "stroke-weight")
        )
        alpha = _adjust_stroke_weight(alpha, base_weight_adjustment)
        random_weight_adjustment = self._random_stroke_weight_adjustment(
            weight_rand,
            random_weight_sigma,
        )
        alpha = _adjust_stroke_weight(alpha, random_weight_adjustment)
        alpha = _vary_ink_density(
            alpha,
            ink_rand,
            jitter=self.config.ink_density_jitter,
            dry_brush_probability=self.config.dry_brush_probability,
            dry_brush_min_opacity=self.config.dry_brush_min_opacity,
        )

        result = Image.new("RGBA", padded.size, self.ink)
        result.putalpha(alpha)
        cropped, _, crop_top = _crop_alpha_with_offset(result, pad=4)
        baseline = (
            round(baseline_px + pad - crop_top)
            if baseline_px is not None
            else max(1, round(cropped.height * 0.76))
        )
        return (cropped, baseline) if return_baseline else cropped

    def _base_stroke_weight_adjustment(
        self,
        alpha: Image.Image,
        math_mode: bool = False,
        reference_weight: float | None = None,
    ) -> float:
        """Normalize the mask toward its text- and font-specific optical weight."""
        optical_weight = _estimate_optical_stroke_weight(alpha)
        if reference_weight is None:
            reference_weight = (
                self.math_reference_stroke_weight
                if math_mode
                else self.reference_stroke_weight
            )
        base_scale = max(0.25, min(3.0, self.config.stroke_weight_base_scale))
        reference_weight *= base_scale
        if optical_weight <= 0 or reference_weight <= 0:
            return 0.0
        return _solve_stroke_weight_adjustment(
            alpha,
            target_weight=reference_weight,
            max_adjustment=MAX_BASE_STROKE_WEIGHT_ADJUSTMENT_PX,
        )

    def _reference_weight_for_text(self, text: str, size_px: int, math_mode: bool = False) -> float:
        """Measure the same glyph mix at the configured reference size."""
        runs = self._font_runs(text, size_px, math=math_mode)
        reference_size = self.math_reference_size_px if math_mode else self.reference_size_px
        fallback_sample = MATH_STROKE_WEIGHT_SAMPLE if math_mode else TEXT_STROKE_WEIGHT_SAMPLE
        weighted_total = 0.0
        total_width = 0.0
        for font_path, run in runs:
            sample = _compact_weight_sample(run, fallback_sample)
            run_width = max(1.0, _measure_text(_load_font(font_path, size_px), run))
            weighted_total += _font_optical_weight(font_path, reference_size, sample) * run_width
            total_width += run_width
        if total_width <= 0:
            return self.math_reference_stroke_weight if math_mode else self.reference_stroke_weight
        return weighted_total / total_width

    def _random_stroke_weight_sigma(self, math_mode: bool = False) -> float:
        """Return the per-edge Gaussian sigma at the shared reference size."""
        # The config describes the standard deviation of total stroke-width
        # variation. Morphology moves both edges, so each edge receives half.
        reference_size = (
            self.reference_size_px
            if self.uses_sdt_trajectories
            else self.math_reference_size_px
            if math_mode
            else self.reference_size_px
        )
        return max(0.0, reference_size * self.config.stroke_weight_variation_sigma_ratio / 2)

    def _random_stroke_weight_adjustment(self, rand: random.Random, sigma: float) -> float:
        if sigma <= 0:
            return 0.0
        # A three-sigma clamp prevents rare Gaussian tails from closing dense
        # counters while retaining a continuous, zero-centered distribution.
        limit = 3.0 * sigma
        return min(limit, max(-limit, rand.gauss(0.0, sigma)))

    def grouped_stroke_weight_adjustment(self, group: str, math_mode: bool = False) -> float:
        """Return one reproducible edge-weight adjustment for a complete writing group."""
        if not self.config.second_layer_enabled:
            return 0.0
        return self._random_stroke_weight_adjustment(
            random.Random(_stable_seed(self.config.seed, "stroke-weight", group)),
            self._random_stroke_weight_sigma(math_mode=math_mode),
        )

    def uniform_pen_width_px(self) -> float:
        """Return the shared text, formula and generated-rule pen width."""
        canonical = max(1.0, self.config.sdt_stroke_width)
        return max(0.5, canonical * self.reference_size_px / 256.0)

    def _trajectory_style(self) -> TrajectoryStyle:
        return TrajectoryStyle(
            rotation_sigma_deg=self._glyph_rotation_sigma_degrees(),
            coordinate_jitter=max(0.0, self.config.sdt_coordinate_jitter),
            jitter_correlation=max(1.0, self.config.sdt_jitter_correlation),
            width_jitter=min(0.8, max(0.0, self.config.sdt_width_jitter)),
            taper=min(0.8, max(0.0, self.config.sdt_taper)),
            supersample=max(1, min(6, self.config.sdt_supersample)),
        )

    def _glyph_rotation_sigma_degrees(self) -> float:
        return max(0.0, math.degrees(self.config.perturb_theta_sigma))

    def _glyph_position_sigma(self, size_px: int, configured: float | None) -> float:
        """Use one position-jitter rule in SDT, Handright and Pillow modes."""
        return max(0.0, configured) if configured is not None else max(0.2, size_px * 0.015)

    def _advance_jitter_sigma(self, size_px: int) -> float:
        return max(0.1, size_px * 0.01)

    def _vertical_position_sigma(self, size_px: int, math_mode: bool = False) -> float:
        if math_mode:
            return max(0.0, size_px * self.config.math_perturb_y_sigma_ratio)
        return self._glyph_position_sigma(size_px, self.config.perturb_y_sigma_px)

    @staticmethod
    def _sample_position_offset(rand: random.Random, sigma: float) -> float:
        """Sample a centered Gaussian offset while rejecting destructive tails."""
        sigma = max(0.0, float(sigma))
        if sigma == 0:
            return 0.0
        limit = 3.0 * sigma
        return min(limit, max(-limit, rand.gauss(0.0, sigma)))

    def _position_jitter_padding(self, x_sigma: float, y_sigma: float) -> int:
        """Reserve enough room for every accepted position-jitter sample."""
        return max(8, math.ceil(3.0 * max(0.0, x_sigma, y_sigma) + 4.0))

    def _estimated_rendered_baseline(
        self,
        text: str,
        size_px: int,
        image: Image.Image,
        math: bool = False,
    ) -> int:
        """Estimate a typographic baseline for fallback renderers after cropping."""
        ink_bbox = image.getchannel("A").getbbox()
        if ink_bbox is None:
            return max(1, round(size_px * 0.75))
        distances: list[int] = []
        for char in text:
            if char.isspace():
                continue
            font = _load_font(self._font_path_for_char(char, size_px, math=math), size_px)
            bbox = font.getbbox(char)
            if bbox is not None:
                distances.append(font.getmetrics()[0] - bbox[1] - self._glyph_vertical_adjustment(char, size_px))
        return max(1, round(ink_bbox[1] + max(distances, default=size_px * 0.75)))

    def _render_with_trajectories(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed: int,
        math: bool = False,
        return_baseline: bool = False,
    ) -> Image.Image | tuple[Image.Image, int]:
        """Compose SDT and derived symbol trajectories directly onto a text line."""
        rand = random.Random(seed)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        pad = max(
            round(size_px * 0.4),
            self._position_jitter_padding(x_sigma, y_sigma),
        )
        runs = self._font_runs(text, size_px, math=math)
        reference_ascent = self._reference_ascent(runs, size_px)
        descent = max(_load_font(font_path, size_px).getmetrics()[1] for font_path, _ in runs)
        max_adjustment = max(self._glyph_vertical_adjustment(char, size_px) for char in text)
        line_height = max(round(size_px * self.config.line_spacing), reference_ascent + descent + 2 * pad + max_adjustment)
        width = max(16, min(max_width + 2 * pad, round(self.measure(text, size_px, math=math) + 2 * pad)))
        image = Image.new("RGBA", (width, line_height), (0, 0, 0, 0))
        x = float(pad)
        baseline = pad + reference_ascent
        style = self._trajectory_style()
        pen_width = self.uniform_pen_width_px()
        for index, char in enumerate(text):
            font_path = self._font_path_for_char(char, size_px, math=math)
            font = _load_font(font_path, size_px)
            advance = max(1.0, _measure_text(font, char))
            if char.isspace():
                x += max(size_px * 0.35, advance)
                continue
            bbox = font.getbbox(char)
            if bbox is None:
                x += advance
                continue
            glyph_width = max(1, bbox[2] - bbox[0])
            glyph_height = max(1, bbox[3] - bbox[1])
            strokes = self.trajectory_store.load(char)
            if strokes is None:
                strokes = font_glyph_strokes(font_path, char)
            if strokes:
                glyph = render_strokes(
                    strokes,
                    glyph_width,
                    glyph_height,
                    pen_width,
                    self.ink,
                    np.random.default_rng(_stable_seed(seed, index, char, "trajectory")),
                    style,
                    em_size=size_px,
                )
            else:
                glyph = Image.new("RGBA", (glyph_width, glyph_height), (0, 0, 0, 0))
                ImageDraw.Draw(glyph).text((-bbox[0], -bbox[1]), char, fill=self.ink, font=font)
            glyph_x = round(x + bbox[0] + self._sample_position_offset(rand, x_sigma))
            glyph_y = round(
                baseline
                - font.getmetrics()[0]
                + bbox[1]
                + self._glyph_vertical_adjustment(char, size_px)
                + self._sample_position_offset(rand, y_sigma)
            )
            image.alpha_composite(glyph, (glyph_x, glyph_y))
            x += (
                advance
                + self.config.word_spacing_px
                + self._sample_position_offset(rand, self._advance_jitter_sigma(size_px))
            )
        cropped, _, crop_top = _crop_alpha_with_offset(image, pad=4)
        rendered_baseline = round(baseline - crop_top)
        return (cropped, rendered_baseline) if return_baseline else cropped

    def _render_with_handright(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False) -> Image.Image:
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        jitter_pad = self._position_jitter_padding(x_sigma, y_sigma)
        pad_x = max(jitter_pad, round(size_px * 0.35))
        pad_y = max(jitter_pad, round(size_px * 0.35))
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
            run_image = self._render_handright_run(
                run,
                size_px,
                max_width,
                _stable_seed(seed, index),
                font_path,
                math_mode=math,
            )
            y = (
                pad_y
                + self._baseline_shift(font_path, size_px, reference_ascent)
                + self._run_vertical_adjustment(run, size_px)
            )
            background.alpha_composite(run_image, (round(x), y))
            x += _measure_text(_load_font(font_path, size_px), run)
        return _crop_alpha(background, pad=4)

    def _render_handright_run(
        self,
        text: str,
        size_px: int,
        max_width: int,
        seed: int,
        font_path: str,
        math_mode: bool = False,
    ) -> Image.Image:
        font = _load_font(font_path, size_px)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math_mode)
        jitter_pad = self._position_jitter_padding(x_sigma, y_sigma)
        pad_x = max(jitter_pad, round(size_px * 0.35))
        pad_y = max(jitter_pad, round(size_px * 0.35))
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
            perturb_x_sigma=x_sigma,
            perturb_y_sigma=y_sigma,
            perturb_theta_sigma=self.config.perturb_theta_sigma,
        )
        image = next(iter(handwrite(text, template, seed=seed))).convert("RGBA")
        return image

    def _render_with_pillow(self, text: str, size_px: int, max_width: int, seed: int, math: bool = False) -> Image.Image:
        rand = random.Random(seed)
        x_sigma = self._glyph_position_sigma(size_px, self.config.perturb_x_sigma_px)
        y_sigma = self._vertical_position_sigma(size_px, math_mode=math)
        pad = max(
            round(size_px * 0.4),
            self._position_jitter_padding(x_sigma, y_sigma),
        )
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
            angle = rand.gauss(0, self._glyph_rotation_sigma_degrees())
            glyph = glyph.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False)
            image.alpha_composite(
                glyph,
                (
                    round(x - pad + self._sample_position_offset(rand, x_sigma)),
                    round(self._sample_position_offset(rand, y_sigma)),
                ),
            )
            x += (
                char_w
                + self.config.word_spacing_px
                + self._sample_position_offset(rand, self._advance_jitter_sigma(size_px))
            )
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
                if starts_with_forbidden_line_punctuation(unit):
                    current = candidate
                else:
                    lines.append(current.strip())
                    current = unit.strip()
            else:
                current = candidate
        if current.strip():
            lines.append(current.strip())
        elif not units:
            lines.append("")
    return lines


def starts_with_forbidden_line_punctuation(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and stripped[0] in FORBIDDEN_LINE_START_PUNCTUATION


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


def _compact_weight_sample(text: str, fallback: str) -> str:
    sample = "".join(char for char in text if not char.isspace())[:32]
    return sample or fallback


@lru_cache(maxsize=512)
def _font_optical_weight(font_path: str, size_px: int, sample: str) -> float:
    font = _load_font(font_path, size_px)
    bbox = font.getbbox(sample)
    if bbox is None:
        return 0.0
    pad = max(4, round(size_px * 0.2))
    width = max(1, bbox[2] - bbox[0] + 2 * pad)
    height = max(1, bbox[3] - bbox[1] + 2 * pad)
    alpha = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(alpha)
    draw.text((pad - bbox[0], pad - bbox[1]), sample, fill=255, font=font)
    return _estimate_optical_stroke_weight(alpha)


def _estimate_stroke_width(alpha: Image.Image, threshold: int = 64) -> float:
    """Estimate mean stroke width from mask area lost after one-pixel erosion."""
    if alpha.width < 3 or alpha.height < 3:
        return 1.0 if alpha.getbbox() is not None else 0.0
    histogram = alpha.histogram()
    area = sum(histogram[threshold:])
    if area <= 0:
        return 0.0
    eroded_histogram = alpha.filter(ImageFilter.MinFilter(3)).histogram()
    inner_area = sum(eroded_histogram[threshold:])
    boundary_area = max(1, area - inner_area)
    return 2.0 * area / boundary_area


def _estimate_optical_stroke_weight(alpha: Image.Image) -> float:
    """Combine silhouette width and antialiased ink density into perceived weight."""
    stroke_width = _estimate_stroke_width(alpha)
    if stroke_width <= 0:
        return 0.0
    histogram = alpha.histogram()
    ink_pixels = sum(histogram[1:])
    if ink_pixels <= 0:
        return 0.0
    ink_mass = sum(value * count for value, count in enumerate(histogram))
    mean_opacity = ink_mass / (255.0 * ink_pixels)
    return stroke_width * math.sqrt(max(0.0, min(1.0, mean_opacity)))


def _solve_stroke_weight_adjustment(
    alpha: Image.Image,
    target_weight: float,
    max_adjustment: float,
) -> float:
    """Find the signed subpixel morphology amount closest to an optical target."""
    current_weight = _estimate_optical_stroke_weight(alpha)
    if current_weight <= 0 or target_weight <= 0 or abs(current_weight - target_weight) < 1e-4:
        return 0.0
    direction = 1.0 if current_weight < target_weight else -1.0
    low = 0.0
    high = max(0.0, max_adjustment)
    best_adjustment = 0.0
    best_error = abs(current_weight - target_weight)
    for _ in range(9):
        magnitude = (low + high) / 2
        adjustment = direction * magnitude
        candidate_weight = _estimate_optical_stroke_weight(
            _adjust_stroke_weight(alpha, adjustment)
        )
        error = abs(candidate_weight - target_weight)
        if error < best_error:
            best_adjustment = adjustment
            best_error = error
        if direction > 0:
            if candidate_weight < target_weight:
                low = magnitude
            else:
                high = magnitude
        elif candidate_weight > target_weight:
            low = magnitude
        else:
            high = magnitude
    endpoint_adjustment = direction * max_adjustment
    endpoint_error = abs(
        _estimate_optical_stroke_weight(_adjust_stroke_weight(alpha, endpoint_adjustment))
        - target_weight
    )
    return endpoint_adjustment if endpoint_error < best_error else best_adjustment


def _adjust_stroke_weight(alpha: Image.Image, adjustment_px: float) -> Image.Image:
    """Apply a signed, subpixel morphological weight adjustment to an ink mask."""
    if abs(adjustment_px) < 1e-6:
        return alpha
    amount = min(MAX_STROKE_WEIGHT_ADJUSTMENT_PX, abs(adjustment_px))
    morphology = ImageFilter.MaxFilter(3) if adjustment_px > 0 else ImageFilter.MinFilter(3)
    full_steps = math.floor(amount)
    adjusted = alpha
    for _ in range(full_steps):
        adjusted = adjusted.filter(morphology)
    fraction = amount - full_steps
    if fraction > 1e-6:
        next_step = adjusted.filter(morphology)
        adjusted = Image.blend(adjusted, next_step, fraction)
    return adjusted


def _warp_ink_mask(
    alpha: Image.Image,
    rand: random.Random,
    elastic_strength: float,
    elastic_smoothness: float,
    baseline_amplitude: float,
    baseline_wavelength: float,
) -> Image.Image:
    """Apply one smooth remap containing local elastic and line-level movement."""
    width, height = alpha.size
    if width <= 1 or height <= 1 or (elastic_strength <= 0 and baseline_amplitude <= 0):
        return alpha

    if elastic_strength > 0:
        dx = _smooth_random_field(width, height, elastic_smoothness, rand) * elastic_strength
        dy = _smooth_random_field(width, height, elastic_smoothness, rand) * elastic_strength
    else:
        dx = np.zeros((height, width), dtype=np.float32)
        dy = np.zeros((height, width), dtype=np.float32)

    if baseline_amplitude > 0:
        phase = rand.uniform(0.0, math.tau)
        x = np.arange(width, dtype=np.float32)
        wave = baseline_amplitude * np.sin(math.tau * x / baseline_wavelength + phase)
        dy += wave[np.newaxis, :]

    return Image.fromarray(_bilinear_remap(np.asarray(alpha, dtype=np.float32), dx, dy), mode="L")


def _smooth_random_field(
    width: int,
    height: int,
    smoothness: float,
    rand: random.Random,
) -> np.ndarray:
    """Create a deterministic, normalized low-frequency displacement field."""
    grid_step = max(2, round(smoothness))
    grid_width = max(3, math.ceil(width / grid_step) + 3)
    grid_height = max(3, math.ceil(height / grid_step) + 3)
    samples = np.fromiter(
        (rand.gauss(0.0, 1.0) for _ in range(grid_width * grid_height)),
        dtype=np.float32,
        count=grid_width * grid_height,
    ).reshape((grid_height, grid_width))
    field_image = Image.fromarray(samples, mode="F").resize((width, height), Image.Resampling.BICUBIC)
    field = np.asarray(field_image, dtype=np.float32)
    standard_deviation = float(field.std())
    if standard_deviation > 1e-6:
        field = field / standard_deviation
    return np.clip(field, -2.5, 2.5)


def _bilinear_remap(source: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Sample a grayscale image through a displacement field without OpenCV."""
    height, width = source.shape
    target_y, target_x = np.indices((height, width), dtype=np.float32)
    source_x = target_x + dx
    source_y = target_y + dy
    valid = (source_x >= 0) & (source_x <= width - 1) & (source_y >= 0) & (source_y <= height - 1)

    source_x = np.clip(source_x, 0, width - 1)
    source_y = np.clip(source_y, 0, height - 1)
    x0 = np.floor(source_x).astype(np.int32)
    y0 = np.floor(source_y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    x_weight = source_x - x0
    y_weight = source_y - y0

    top = source[y0, x0] * (1.0 - x_weight) + source[y0, x1] * x_weight
    bottom = source[y1, x0] * (1.0 - x_weight) + source[y1, x1] * x_weight
    remapped = top * (1.0 - y_weight) + bottom * y_weight
    remapped[~valid] = 0
    return np.clip(remapped, 0, 255).astype(np.uint8)


def _vary_ink_density(
    alpha: Image.Image,
    rand: random.Random,
    jitter: float,
    dry_brush_probability: float,
    dry_brush_min_opacity: float,
) -> Image.Image:
    """Add slow ink-flow variation and occasional directional dry-brush fading."""
    jitter = min(1.0, max(0.0, jitter))
    dry_brush_probability = min(1.0, max(0.0, dry_brush_probability))
    dry_brush_min_opacity = min(1.0, max(0.0, dry_brush_min_opacity))
    if jitter <= 0 and (dry_brush_probability <= 0 or dry_brush_min_opacity >= 1):
        return alpha

    values = np.asarray(alpha, dtype=np.float32).copy()
    height, width = values.shape
    if jitter > 0:
        phase = rand.uniform(0.0, math.tau)
        cycles = rand.uniform(0.5, 1.8)
        x = np.linspace(0.0, math.tau * cycles, width, dtype=np.float32)
        flow = 1.0 - jitter * (0.3 + 0.7 * (0.5 + 0.5 * np.sin(x + phase)))
        values *= flow[np.newaxis, :]

    if rand.random() < dry_brush_probability and dry_brush_min_opacity < 1:
        direction = rand.choice(("left", "right", "top", "bottom"))
        length = width if direction in {"left", "right"} else height
        gradient = np.linspace(dry_brush_min_opacity, 1.0, length, dtype=np.float32)
        if direction in {"right", "bottom"}:
            gradient = gradient[::-1]
        values *= gradient[np.newaxis, :] if direction in {"left", "right"} else gradient[:, np.newaxis]

    return Image.fromarray(np.clip(values, 0, 255).astype(np.uint8), mode="L")


@lru_cache(maxsize=4096)
def _has_glyph(font_path: str, size_px: int, char: str) -> bool:
    font = _load_font(font_path, size_px)
    missing = "\u0378"
    return (font.getbbox(char), bytes(font.getmask(char))) != (
        font.getbbox(missing),
        bytes(font.getmask(missing)),
    )


def _crop_alpha(image: Image.Image, pad: int = 0) -> Image.Image:
    return _crop_alpha_with_offset(image, pad)[0]


def _crop_alpha_with_offset(image: Image.Image, pad: int = 0) -> tuple[Image.Image, int, int]:
    """Crop transparent margins and retain the origin needed for baseline tracking."""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, image.height), (0, 0, 0, 0)), 0, 0
    left = max(0, bbox[0] - pad)
    top = max(0, bbox[1] - pad)
    right = min(image.width, bbox[2] + pad)
    bottom = min(image.height, bbox[3] + pad)
    return image.crop((left, top, right, bottom)), left, top


def _stable_seed(*parts: object) -> int:
    joined = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)
