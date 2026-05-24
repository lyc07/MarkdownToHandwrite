from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from PIL import ImageColor


@dataclass
class PageConfig:
    width_mm: float = 210.0
    height_mm: float = 297.0
    dpi: int = 180
    margin_top_mm: float = 54.0
    margin_bottom_mm: float = 20.0
    margin_left_mm: float = 22.0
    margin_right_mm: float = 20.0


@dataclass
class BackgroundConfig:
    style: str = "lined"
    image: str | None = None
    auto_discover: bool = True
    paper_color: str = "#fffdf4"
    line_color: str = "#d7e4ef"
    margin_line_color: str = "#edb2aa"
    line_gap_mm: float = 8.0
    grid_size_mm: float = 8.0
    dot_gap_mm: float = 5.0
    dot_radius_px: int = 1
    draw_margin_line: bool = True


@dataclass
class HandwritingConfig:
    font_path: str | None = None
    math_font_path: str | None = None
    fallback_font_path: str | None = None
    ink_color: str = "#17233b"
    body_font_pt: float = 13.5
    math_font_pt: float = 14.0
    code_font_pt: float = 11.5
    h1_font_pt: float = 22.0
    h2_font_pt: float = 17.0
    h3_font_pt: float = 15.0
    line_spacing: float = 1.55
    word_spacing_px: int = -1
    perturb_theta_sigma: float = 0.045
    perturb_x_sigma_px: float | None = None
    perturb_y_sigma_px: float | None = None
    seed: int | str | None = 2026
    prefer_handright: bool = True


@dataclass
class LayoutConfig:
    number_sections: bool = True
    paragraph_gap_mm: float = 2.2
    heading_gap_before_mm: float = 5.0
    heading_gap_after_mm: float = 3.0
    formula_gap_mm: float = 3.0
    table_gap_mm: float = 4.0
    table_cell_padding_mm: float = 2.0
    first_line_indent_em: float = 2.0
    list_indent_mm: float = 7.0
    image_placeholder_height_mm: float = 65.0
    image_placeholder_border: bool = True
    footer_gap_mm: float = 8.0


@dataclass
class ReportConfig:
    page: PageConfig = field(default_factory=PageConfig)
    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    handwriting: HandwritingConfig = field(default_factory=HandwritingConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)


def load_config(path: str | Path | None = None) -> ReportConfig:
    config = ReportConfig()
    if path is None:
        return config
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _update_dataclass(config, data)
    return config


def _update_dataclass(target: Any, data: dict[str, Any]) -> None:
    known_fields = {field.name for field in fields(target)}
    for key, value in data.items():
        if key not in known_fields:
            raise ValueError(f"Unknown config field: {key}")
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _update_dataclass(current, value)
        else:
            setattr(target, key, value)


def mm_to_px(mm: float, dpi: int) -> int:
    return round(mm / 25.4 * dpi)


def pt_to_px(pt: float, dpi: int) -> int:
    return max(1, round(pt / 72.0 * dpi))


def color(value: str, alpha: int | None = None) -> tuple[int, ...]:
    rgb = ImageColor.getrgb(value)
    if alpha is None:
        return rgb
    return (*rgb, alpha)
