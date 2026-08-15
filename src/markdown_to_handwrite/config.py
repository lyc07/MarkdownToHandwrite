from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from PIL import ImageColor


@dataclass
class PageConfig:
    width_mm: float = 210.0  # 纸张宽度，单位 mm；默认 A4 宽度。
    height_mm: float = 297.0  # 纸张高度，单位 mm；默认 A4 高度。
    dpi: int = 300  # 栅格渲染分辨率；越高越清晰，但生成时间和文件体积也越大。
    margin_top_mm: float = 54.0  # 正文区域上边距，单位 mm。
    margin_bottom_mm: float = 20.0  # 正文区域下边距，单位 mm。
    margin_left_mm: float = 22.0  # 正文区域左边距，单位 mm。
    margin_right_mm: float = 20.0  # 正文区域右边距，单位 mm。


@dataclass
class BackgroundConfig:
    style: str = "lined"  # 纸张样式：plain、lined、grid、dot 或 image。
    image: str | None = None  # 背景图片或 PDF 路径；仅 image 样式使用，None 表示未指定。
    auto_discover: bool = True  # image 样式未指定路径时，是否自动搜索 background/ 素材。
    paper_color: str = "#fffdf4"  # 程序生成纸张的底色，使用十六进制颜色。
    line_color: str = "#d7e4ef"  # 横线、方格线和点阵的颜色。
    margin_line_color: str = "#edb2aa"  # 左侧页边参考线的颜色。
    line_gap_mm: float = 8.0  # 横线纸相邻横线的间距，单位 mm。
    grid_size_mm: float = 8.0  # 方格纸单格边长，单位 mm。
    dot_gap_mm: float = 5.0  # 点阵纸相邻点的间距，单位 mm。
    dot_radius_px: int = 1  # 点阵圆点半径，单位输出像素。
    draw_margin_line: bool = True  # 是否绘制左侧红色页边参考线。


@dataclass
class HandwritingConfig:
    font_path: str | None = None  # 正文字体路径；None 时按项目字体和系统字体顺序自动选择。
    math_font_path: str | None = None  # 数学字符字体路径；None 时沿用正文字体链。
    fallback_font_path: str | None = None  # 首选字体缺字时使用的额外回退字体路径。
    ink_color: str = "#17233b"  # 正文、公式和生成线条共用的墨水颜色。
    body_font_pt: float = 16.0  # 正文字号，单位 pt。
    math_font_pt: float = 16.0  # 展示公式及行内公式主字符字号，单位 pt。
    code_font_pt: float = 11.5  # 代码块字号，单位 pt。
    h1_font_pt: float = 22.0  # 一级标题字号，单位 pt；不会额外加粗。
    h2_font_pt: float = 17.0  # 二级标题字号，单位 pt；不会额外加粗。
    h3_font_pt: float = 15.0  # 三级标题字号，单位 pt；不会额外加粗。
    line_spacing: float = 1.55  # 行高相对于当前字号的倍数。
    word_spacing_px: int = -1  # 每个字符排版前进量的附加像素；负值表示适度收紧。
    perturb_theta_sigma: float = 0.008  # 字符旋转角度的正态分布标准差，单位 rad。
    perturb_x_sigma_px: float | None = None  # 字符水平偏移标准差，单位 px；None 时取字号的 1.5%。
    perturb_y_sigma_px: float | None = None  # 正文字符垂直偏移标准差，单位 px；None 时取字号的 1.5%。
    math_perturb_y_sigma_ratio: float = 0.015  # 公式字符垂直偏移标准差，相对各字符当前字号的比例。
    sdt_trajectory_enabled: bool = True  # 是否优先使用 SDT 在线轨迹直接渲染字符。
    sdt_trajectory_path: str | None = None  # SDT 轨迹库路径；None 时使用项目内置轨迹包。
    sdt_stroke_width: float = 16.0  # 统一基础笔画粗细，按 SDT 256 单位画布定义。
    sdt_coordinate_jitter: float = 0.6  # 沿轨迹施加的低频平滑坐标扰动幅度。
    sdt_jitter_correlation: float = 10.0  # 坐标和笔压噪声的平滑相关长度，单位重采样点。
    sdt_width_jitter: float = 0.15  # 沿单条笔画变化的相对笔压标准差。
    sdt_taper: float = 0.30  # 起笔、收笔相对于主体笔宽的渐细比例。
    sdt_supersample: int = 3  # 轨迹渲染超采样倍数，用于改善抗锯齿质量。
    second_layer_enabled: bool = True  # 是否启用栅格化后的形变、字重和墨色后处理。
    elastic_strength_ratio: float = 0.003  # 局部弹性形变幅度，相对于当前字号的比例。
    elastic_smoothness_ratio: float = 0.55  # 弹性位移场的平滑尺度，相对于当前字号的比例。
    baseline_wave_amplitude_ratio: float = 0.018  # 整行基线起伏幅度，相对于当前字号的比例。
    baseline_wave_length_em: float = 12.0  # 基线正弦起伏的波长，单位 em。
    stroke_weight_base_scale: float = 1.0  # 回退字体目标基础字重倍率；SDT 模式不使用。
    stroke_weight_variation_sigma_ratio: float = 0.0035  # 整组文字或公式粗细变化的正态分布标准差，单位 em。
    ink_density_jitter: float = 0.08  # 墨水浓淡沿笔迹缓慢变化的幅度，范围 0 到 1。
    dry_brush_probability: float = 0.08  # 每个文字或线条图块出现轻微飞白的概率。
    dry_brush_min_opacity: float = 0.72  # 飞白区域允许达到的最低不透明度，范围 0 到 1。
    math_rule_tilt_ratio: float = 0.048  # 分数线、根号线和表格线的随机倾斜幅度，单位 em。
    math_rule_wobble_ratio: float = 0.012  # 公式线和表格线的低频弯曲幅度，单位 em。
    math_rule_jitter_ratio: float = 0.050  # 公式线和表格线的细小路径抖动幅度，单位 em。
    seed: int | str | None = 2026  # 全局随机种子；相同值生成可复现结果，None 会作为空种子稳定复现。
    prefer_handright: bool = True  # SDT 不可用或关闭时，是否优先使用 Handright 回退引擎。


@dataclass
class LayoutConfig:
    number_sections: bool = False  # 是否自动为一至三级标题添加章节编号。
    show_page_numbers: bool = False  # 是否在页面底部绘制页码。
    paragraph_gap_mm: float = 2.2  # 段落结束后的垂直间距，单位 mm。
    heading_gap_before_mm: float = 5.0  # 标题前的垂直间距，单位 mm。
    heading_gap_after_mm: float = 3.0  # 标题后的垂直间距，单位 mm。
    formula_gap_mm: float = 3.0  # 展示公式上下两侧的留白，单位 mm。
    table_gap_mm: float = 4.0  # 表格与上下正文之间的间距，单位 mm。
    table_cell_padding_mm: float = 2.0  # 表格单元格内容与边框的内边距，单位 mm。
    first_line_indent_em: float = 2.0  # 普通段落首行缩进，单位 em。
    list_indent_mm: float = 7.0  # 有序和无序列表内容的左缩进，单位 mm。
    image_placeholder_height_mm: float = 65.0  # 图片占位框高度，单位 mm。
    image_placeholder_border: bool = True  # 是否绘制图片占位框边框。
    footer_gap_mm: float = 8.0  # 启用页码时为页脚预留的正文禁入高度，单位 mm。


@dataclass
class ReportConfig:
    page: PageConfig = field(default_factory=PageConfig)  # 页面尺寸、分辨率和页边距。
    background: BackgroundConfig = field(default_factory=BackgroundConfig)  # 纸张背景及辅助线样式。
    handwriting: HandwritingConfig = field(default_factory=HandwritingConfig)  # 字体、轨迹及两层笔迹扰动。
    layout: LayoutConfig = field(default_factory=LayoutConfig)  # 标题、段落、公式、表格和页脚布局。


def load_config(path: str | Path | None = None) -> ReportConfig:
    config = ReportConfig()
    if path is None:
        return config
    data = _migrate_config(json.loads(Path(path).read_text(encoding="utf-8")))
    _update_dataclass(config, data)
    return config


def config_from_dict(data: dict[str, Any]) -> ReportConfig:
    """Build a report configuration from an already decoded JSON object."""
    if not isinstance(data, dict):
        raise TypeError("Config must be a JSON object.")
    data = _migrate_config(data)
    config = ReportConfig()
    _update_dataclass(config, data)
    return config


def _migrate_config(data: dict[str, Any]) -> dict[str, Any]:
    """Translate the former probability-plus-amplitude weight model to sigma."""
    migrated = deepcopy(data)
    handwriting = migrated.get("handwriting")
    if not isinstance(handwriting, dict):
        return migrated

    legacy_ratio = handwriting.pop("stroke_weight_variation_ratio", None)
    legacy_probability = handwriting.pop("stroke_weight_variation_probability", None)
    if (
        "stroke_weight_variation_sigma_ratio" not in handwriting
        and (legacy_ratio is not None or legacy_probability is not None)
    ):
        amplitude = max(0.0, float(0.012 if legacy_ratio is None else legacy_ratio))
        probability = min(1.0, max(0.0, float(0.22 if legacy_probability is None else legacy_probability)))
        # Var[p * Uniform(-a, a)] = p*a^2/3. Preserve the old RMS
        # strength while replacing its point mass at zero with N(0, sigma^2).
        handwriting["stroke_weight_variation_sigma_ratio"] = amplitude * math.sqrt(probability / 3.0)
    return migrated


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
