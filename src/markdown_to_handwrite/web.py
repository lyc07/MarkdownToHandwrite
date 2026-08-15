from __future__ import annotations

import argparse
import json
import math
import mimetypes
import secrets
import threading
import webbrowser
from dataclasses import asdict, fields, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image, ImageColor

from .config import ReportConfig, config_from_dict
from .markdown_parser import parse_markdown
from .renderer import PROJECT_ROOT, ReportRenderer


STATIC_ROOT = Path(__file__).resolve().parent / "webui"
OUTPUT_ROOT = PROJECT_ROOT / "output" / "webui"
MAX_REQUEST_BYTES = 4 * 1024 * 1024


def _range(
    path: str,
    label: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: str = "",
    help_text: str = "",
) -> dict[str, Any]:
    return {
        "path": path,
        "label": label,
        "control": "range",
        "min": minimum,
        "max": maximum,
        "step": step,
        "unit": unit,
        "help": help_text,
    }


def _toggle(path: str, label: str, help_text: str = "") -> dict[str, Any]:
    return {"path": path, "label": label, "control": "toggle", "help": help_text}


def _text(path: str, label: str, help_text: str = "", control: str = "text") -> dict[str, Any]:
    return {"path": path, "label": label, "control": control, "help": help_text}


def _nullable_range(
    path: str,
    label: str,
    minimum: float,
    maximum: float,
    step: float,
    unit: str = "px",
    help_text: str = "",
) -> dict[str, Any]:
    item = _range(path, label, minimum, maximum, step, unit, help_text)
    item["control"] = "nullable-range"
    return item


CONFIG_SECTIONS: list[dict[str, Any]] = [
    {
        "id": "page",
        "title": "页面与分辨率",
        "eyebrow": "PAGE",
        "description": "纸张尺寸、输出精度与四周留白",
        "fields": [
            _range("page.width_mm", "纸张宽度", 120, 420, 1, "mm"),
            _range("page.height_mm", "纸张高度", 120, 594, 1, "mm"),
            _range("page.dpi", "输出 DPI", 96, 600, 12, "dpi", "DPI 越高越清晰，也会显著增加生成时间。"),
            _range("page.margin_top_mm", "上边距", 0, 90, 1, "mm"),
            _range("page.margin_bottom_mm", "下边距", 0, 90, 1, "mm"),
            _range("page.margin_left_mm", "左边距", 0, 70, 1, "mm"),
            _range("page.margin_right_mm", "右边距", 0, 70, 1, "mm"),
        ],
    },
    {
        "id": "background",
        "title": "纸张与背景",
        "eyebrow": "PAPER",
        "description": "底色、纸面纹理与参考背景",
        "fields": [
            {
                "path": "background.style",
                "label": "纸张样式",
                "control": "select",
                "options": [
                    {"value": "plain", "label": "纯色纸"},
                    {"value": "lined", "label": "横线纸"},
                    {"value": "grid", "label": "方格纸"},
                    {"value": "dot", "label": "点阵纸"},
                    {"value": "image", "label": "背景素材"},
                ],
                "help": "纯色、横线、方格和点阵由程序绘制；选择背景素材时才读取背景文件或自动发现素材。",
            },
            _text("background.image", "背景文件", "选择文件后自动切换到“背景素材”；留空时可使用自动发现。", "background-path"),
            _toggle("background.auto_discover", "自动发现背景", "仅在纸张样式为“背景素材”且未指定文件时搜索 background/ 目录。"),
            _text("background.paper_color", "纸张底色", control="color"),
            _text("background.line_color", "辅助线颜色", control="color"),
            _text("background.margin_line_color", "页边线颜色", control="color"),
            _range("background.line_gap_mm", "横线间距", 3, 20, 0.5, "mm"),
            _range("background.grid_size_mm", "方格尺寸", 3, 20, 0.5, "mm"),
            _range("background.dot_gap_mm", "点阵间距", 2, 15, 0.5, "mm"),
            _range("background.dot_radius_px", "点阵半径", 1, 6, 1, "px"),
            _toggle("background.draw_margin_line", "绘制页边线"),
        ],
    },
    {
        "id": "typography",
        "title": "字体与字号",
        "eyebrow": "TYPE",
        "description": "只决定字符尺寸、排版度量和非 SDT 符号的中心线形状",
        "fields": [
            _text("handwriting.font_path", "正文字体", "SDT 中文不使用其轮廓；该字体负责排版度量，以及英文、数字和缺失符号的中心线形状。", "font-path"),
            _text("handwriting.math_font_path", "数学字体", "只决定数学符号的排版度量与中心线形状；留空时沿用正文字体。", "font-path"),
            _text("handwriting.fallback_font_path", "回退字体", "仅在首选字体缺少字符时补齐字形。", "font-path"),
            _range("handwriting.body_font_pt", "正文字号", 7, 32, 0.5, "pt", "控制正文字符边界框与排版尺寸，不改变统一基础笔宽。"),
            _range("handwriting.math_font_pt", "数学字号", 7, 36, 0.5, "pt", "控制公式主字符尺寸；上下标由公式布局按比例缩放，笔宽保持统一。"),
            _range("handwriting.code_font_pt", "代码字号", 6, 28, 0.5, "pt", "只控制代码字符尺寸。"),
            _range("handwriting.h1_font_pt", "一级标题", 12, 48, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.h2_font_pt", "二级标题", 10, 40, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.h3_font_pt", "三级标题", 9, 34, 0.5, "pt", "只放大字符结构，不额外加粗。"),
            _range("handwriting.line_spacing", "行距倍率", 1.0, 2.5, 0.01, "×", "只控制行框高度，不改变字符形状或笔画粗细。"),
            _range("handwriting.word_spacing_px", "字间距", -12, 24, 1, "px", "统一加到所有字符的排版前进宽度。"),
        ],
    },
    {
        "id": "sdt-trajectories",
        "title": "SDT · 轨迹渲染",
        "eyebrow": "STROKE",
        "description": "直接重绘在线笔迹，并统一正文、标题、公式与表格线的笔宽",
        "fields": [
            _toggle("handwriting.sdt_trajectory_enabled", "启用 SDT 轨迹引擎", "中文优先读取 SDT 轨迹；缺失符号自动提取字体中心线。"),
            _text("handwriting.sdt_trajectory_path", "轨迹库路径", "留空时使用项目内置的 6763 字轨迹包。"),
            _range("handwriting.sdt_stroke_width", "统一基础笔宽", 6, 22, 0.5, "SDT", "唯一的 SDT 基础粗细参数；按正文字号换算后，同样用于标题、公式字符、分数线和表格线。"),
            _range("handwriting.sdt_supersample", "抗锯齿采样", 1, 5, 1, "×", "只影响边缘质量和生成速度，不改变布局、形状和目标笔宽。"),
        ],
    },
    {
        "id": "first-layer",
        "title": "字形扰动",
        "eyebrow": "GLYPH",
        "description": "只改变字符和笔画的几何形状，不改变墨色与基础笔宽",
        "fields": [
            _toggle("handwriting.prefer_handright", "优先使用 Handright", "仅在关闭或无法加载 SDT 轨迹引擎时生效。"),
            _range("handwriting.perturb_theta_sigma", "字符旋转标准差", 0, 0.06, 0.001, "rad", "所有引擎统一按弧度解释；默认 0.008 rad，约等于 0.46°。"),
            _nullable_range("handwriting.perturb_x_sigma_px", "字符水平偏移", 0, 12, 0.1, "px", "自动时统一使用当前字号的 1.5%。"),
            _nullable_range("handwriting.perturb_y_sigma_px", "正文字符垂直偏移", 0, 12, 0.1, "px", "只控制正文、标题、列表编号和页码字符；自动时使用当前字号的 1.5%。"),
            _range("handwriting.math_perturb_y_sigma_ratio", "公式字符垂直偏移 σ", 0, 0.10, 0.001, "em", "实际标准差等于当前公式字符字号乘以该比例；主字符、上下标及分式组件分别按各自字号计算，不移动分数线或根号线。"),
            _range("handwriting.sdt_coordinate_jitter", "笔画路径扰动", 0, 2.0, 0.05, "SDT", "应用于所有轨迹字符；SDT 汉字与字体中心线符号会先按弧长统一采样。"),
            _range("handwriting.sdt_jitter_correlation", "路径扰动平滑长度", 2, 30, 0.5, "采样点", "越大越平缓；统一采样后不再受原始轨迹点数影响。"),
            _range("handwriting.elastic_strength_ratio", "行内弹性形变", 0, 0.1, 0.001, "em", "栅格化后对整行文字或整组公式施加局部形变。"),
            _range("handwriting.elastic_smoothness_ratio", "弹性平滑尺度", 0.1, 2.0, 0.01, "em", "控制弹性位移场的变化尺度。"),
            _range("handwriting.baseline_wave_amplitude_ratio", "基线起伏", 0, 0.08, 0.001, "em", "统一作用于正文行和公式字符图块。"),
            _range("handwriting.baseline_wave_length_em", "基线波长", 2, 24, 0.5, "em", "越大时整行起伏越舒缓。"),
            _range("handwriting.math_rule_tilt_ratio", "生成线条倾斜", 0, 0.12, 0.001, "em", "只改变分数线、根号横线和表格线的方向。"),
            _range("handwriting.math_rule_wobble_ratio", "生成线条弯曲", 0, 0.05, 0.001, "em", "为公式线和表格线加入低频平缓弯曲。"),
            _range("handwriting.math_rule_jitter_ratio", "生成线条抖动", 0, 0.1, 0.001, "em", "为生成线条加入细小路径扰动；不改变墨色或基础笔宽。"),
            _text("handwriting.seed", "随机种子", "统一控制字形、笔压、墨色和公式线条；相同种子可复现。"),
        ],
    },
    {
        "id": "second-layer",
        "title": "墨迹扰动",
        "eyebrow": "INK",
        "description": "只改变笔压、整体粗细与墨色；同样作用于字符和生成线条",
        "fields": [
            _text("handwriting.ink_color", "统一墨水颜色", "正文、标题、公式字符和生成线条共用。", control="color"),
            _range("handwriting.sdt_width_jitter", "沿笔画笔压变化", 0, 0.35, 0.01, "", "统一作用于 SDT 汉字、中心线符号、公式线和表格线。"),
            _range("handwriting.sdt_taper", "起收笔渐细", 0, 0.6, 0.01, "", "控制每条轨迹及生成线条首尾的收尖程度。"),
            _toggle("handwriting.second_layer_enabled", "启用栅格墨迹后处理", "控制整体字重随机、墨色波动和飞白；关闭时仍保留上面的轨迹级笔压与收笔。"),
            _range("handwriting.stroke_weight_base_scale", "回退字体基础字重", 0.6, 1.6, 0.01, "×", "仅在 Handright/Pillow 回退模式下生效；SDT 模式只使用“统一基础笔宽”。"),
            _range("handwriting.stroke_weight_variation_sigma_ratio", "整体粗细扰动 σ", 0, 0.03, 0.0005, "em", "零均值正态分布的标准差；0 表示关闭。同一公式的字符、分数线、根号线与重音线共享一次连续粗细扰动。"),
            _range("handwriting.ink_density_jitter", "墨水浓淡波动", 0, 0.5, 0.01, "", "统一作用于字符墨迹、公式线与表格线。"),
            _range("handwriting.dry_brush_probability", "飞白概率", 0, 1, 0.01, "", "字符和生成线条使用同一概率。"),
            _range("handwriting.dry_brush_min_opacity", "飞白最低浓度", 0.1, 1, 0.01, "", "值越低，触发飞白时的墨迹越淡。"),
        ],
    },
    {
        "id": "footer",
        "title": "页脚与页码",
        "eyebrow": "FOOTER",
        "description": "控制页面底部页码及其独立预留空间",
        "fields": [
            _toggle("layout.show_page_numbers", "显示底部页码", "关闭后不绘制页码，也不为页脚预留空间。"),
            _range("layout.footer_gap_mm", "页码区域高度", 0, 24, 0.5, "mm", "仅在显示底部页码时参与正文分页。"),
        ],
    },
    {
        "id": "layout",
        "title": "文档布局",
        "eyebrow": "LAYOUT",
        "description": "标题编号、段落节奏、表格与图片留白",
        "fields": [
            _toggle("layout.number_sections", "自动编号章节"),
            _range("layout.paragraph_gap_mm", "段后间距", 0, 12, 0.1, "mm"),
            _range("layout.heading_gap_before_mm", "标题前间距", 0, 18, 0.5, "mm"),
            _range("layout.heading_gap_after_mm", "标题后间距", 0, 14, 0.5, "mm"),
            _range("layout.formula_gap_mm", "公式上下间距", 0, 14, 0.5, "mm"),
            _range("layout.table_gap_mm", "表格上下间距", 0, 16, 0.5, "mm"),
            _range("layout.table_cell_padding_mm", "单元格内边距", 0, 8, 0.25, "mm"),
            _range("layout.first_line_indent_em", "首行缩进", 0, 6, 0.25, "em"),
            _range("layout.list_indent_mm", "列表缩进", 0, 24, 0.5, "mm"),
            _range("layout.image_placeholder_height_mm", "图片占位高度", 10, 160, 1, "mm"),
            _toggle("layout.image_placeholder_border", "图片占位边框"),
        ],
    },
]


_DEFAULT_HANDWRITING = ReportConfig().handwriting


STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "formal": {
        "handwriting.perturb_theta_sigma": 0.004,
        "handwriting.math_perturb_y_sigma_ratio": 0.008,
        "handwriting.sdt_coordinate_jitter": 0.35,
        "handwriting.sdt_jitter_correlation": 14.0,
        "handwriting.elastic_strength_ratio": 0.001,
        "handwriting.elastic_smoothness_ratio": 0.75,
        "handwriting.baseline_wave_amplitude_ratio": 0.008,
        "handwriting.baseline_wave_length_em": 16.0,
        "handwriting.math_rule_tilt_ratio": 0.022,
        "handwriting.math_rule_wobble_ratio": 0.005,
        "handwriting.math_rule_jitter_ratio": 0.025,
        "handwriting.sdt_width_jitter": 0.08,
        "handwriting.sdt_taper": 0.24,
        "handwriting.stroke_weight_variation_sigma_ratio": 0.0020,
        "handwriting.ink_density_jitter": 0.04,
        "handwriting.dry_brush_probability": 0.02,
        "handwriting.dry_brush_min_opacity": 0.86,
    },
    "natural": {
        "handwriting.perturb_theta_sigma": _DEFAULT_HANDWRITING.perturb_theta_sigma,
        "handwriting.math_perturb_y_sigma_ratio": _DEFAULT_HANDWRITING.math_perturb_y_sigma_ratio,
        "handwriting.sdt_coordinate_jitter": _DEFAULT_HANDWRITING.sdt_coordinate_jitter,
        "handwriting.sdt_jitter_correlation": _DEFAULT_HANDWRITING.sdt_jitter_correlation,
        "handwriting.elastic_strength_ratio": _DEFAULT_HANDWRITING.elastic_strength_ratio,
        "handwriting.elastic_smoothness_ratio": _DEFAULT_HANDWRITING.elastic_smoothness_ratio,
        "handwriting.baseline_wave_amplitude_ratio": _DEFAULT_HANDWRITING.baseline_wave_amplitude_ratio,
        "handwriting.baseline_wave_length_em": _DEFAULT_HANDWRITING.baseline_wave_length_em,
        "handwriting.math_rule_tilt_ratio": _DEFAULT_HANDWRITING.math_rule_tilt_ratio,
        "handwriting.math_rule_wobble_ratio": _DEFAULT_HANDWRITING.math_rule_wobble_ratio,
        "handwriting.math_rule_jitter_ratio": _DEFAULT_HANDWRITING.math_rule_jitter_ratio,
        "handwriting.sdt_width_jitter": _DEFAULT_HANDWRITING.sdt_width_jitter,
        "handwriting.sdt_taper": _DEFAULT_HANDWRITING.sdt_taper,
        "handwriting.stroke_weight_variation_sigma_ratio": _DEFAULT_HANDWRITING.stroke_weight_variation_sigma_ratio,
        "handwriting.ink_density_jitter": _DEFAULT_HANDWRITING.ink_density_jitter,
        "handwriting.dry_brush_probability": _DEFAULT_HANDWRITING.dry_brush_probability,
        "handwriting.dry_brush_min_opacity": _DEFAULT_HANDWRITING.dry_brush_min_opacity,
    },
    "casual": {
        "handwriting.perturb_theta_sigma": 0.014,
        "handwriting.math_perturb_y_sigma_ratio": 0.028,
        "handwriting.sdt_coordinate_jitter": 0.95,
        "handwriting.sdt_jitter_correlation": 7.0,
        "handwriting.elastic_strength_ratio": 0.006,
        "handwriting.elastic_smoothness_ratio": 0.40,
        "handwriting.baseline_wave_amplitude_ratio": 0.036,
        "handwriting.baseline_wave_length_em": 8.0,
        "handwriting.math_rule_tilt_ratio": 0.078,
        "handwriting.math_rule_wobble_ratio": 0.022,
        "handwriting.math_rule_jitter_ratio": 0.082,
        "handwriting.sdt_width_jitter": 0.24,
        "handwriting.sdt_taper": 0.38,
        "handwriting.stroke_weight_variation_sigma_ratio": 0.0055,
        "handwriting.ink_density_jitter": 0.16,
        "handwriting.dry_brush_probability": 0.20,
        "handwriting.dry_brush_min_opacity": 0.58,
    },
}


def _config_paths(value: Any, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    if not is_dataclass(value):
        return paths
    for field_info in fields(value):
        field_value = getattr(value, field_info.name)
        path = f"{prefix}.{field_info.name}" if prefix else field_info.name
        if is_dataclass(field_value):
            paths.update(_config_paths(field_value, path))
        else:
            paths.add(path)
    return paths


def schema_paths() -> set[str]:
    return {item["path"] for section in CONFIG_SECTIONS for item in section["fields"]}


def available_assets() -> dict[str, list[dict[str, str]]]:
    fonts = []
    for path in sorted((PROJECT_ROOT / "font").glob("*")):
        if path.is_file() and path.suffix.lower() in {".ttf", ".otf", ".ttc"}:
            fonts.append({"label": path.name, "value": path.relative_to(PROJECT_ROOT).as_posix()})

    backgrounds = []
    candidates = list((PROJECT_ROOT / "background").glob("*"))
    candidates.extend(path for path in PROJECT_ROOT.iterdir() if path.is_file())
    for path in sorted(set(candidates)):
        if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            backgrounds.append({"label": path.name, "value": path.relative_to(PROJECT_ROOT).as_posix()})
    return {"fonts": fonts, "backgrounds": backgrounds}


def available_examples() -> list[dict[str, str]]:
    examples = []
    for path in sorted((PROJECT_ROOT / "examples").glob("*.md")):
        examples.append({"label": path.stem, "value": path.name})
    return examples


def build_bootstrap() -> dict[str, Any]:
    return {
        "config": asdict(ReportConfig()),
        "sections": CONFIG_SECTIONS,
        "presets": STYLE_PRESETS,
        "assets": available_assets(),
        "examples": available_examples(),
    }


def validate_config(config: ReportConfig) -> None:
    if not 4.0 <= config.handwriting.sdt_stroke_width <= 32.0:
        raise ValueError("SDT 统一笔画粗细必须在 4 到 32 之间。")
    if not 1 <= config.handwriting.sdt_supersample <= 8:
        raise ValueError("SDT 抗锯齿采样必须在 1 到 8 之间。")
    if not 0.25 <= config.handwriting.stroke_weight_base_scale <= 3.0:
        raise ValueError("基础字重倍率必须在 0.25 到 3.0 之间。")
    if not 0.0 <= config.handwriting.stroke_weight_variation_sigma_ratio <= 0.1:
        raise ValueError("整体粗细扰动 σ 必须在 0 到 0.1 em 之间。")
    if not 0.0 <= config.handwriting.math_perturb_y_sigma_ratio <= 0.25:
        raise ValueError("公式字符垂直偏移 σ 必须在 0 到 0.25 em 之间。")
    if not 72 <= config.page.dpi <= 1200:
        raise ValueError("DPI 必须在 72 到 1200 之间。")
    if config.page.width_mm <= 0 or config.page.height_mm <= 0:
        raise ValueError("页面宽高必须大于 0。")
    if config.page.margin_left_mm + config.page.margin_right_mm >= config.page.width_mm:
        raise ValueError("左右边距之和不能超过页面宽度。")
    if config.page.margin_top_mm + config.page.margin_bottom_mm >= config.page.height_mm:
        raise ValueError("上下边距之和不能超过页面高度。")
    if config.background.style not in {"plain", "lined", "grid", "dot", "image"}:
        raise ValueError("不支持的背景样式。")
    for value in (
        config.background.paper_color,
        config.background.line_color,
        config.background.margin_line_color,
        config.handwriting.ink_color,
    ):
        ImageColor.getrgb(value)
    for path in schema_paths():
        section_name, field_name = path.split(".", 1)
        value = getattr(getattr(config, section_name), field_name)
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"参数 {path} 不是有限数值。")


class RenderBusyError(RuntimeError):
    pass


class RenderService:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.output_root = output_root
        self.lock = threading.Lock()

    def render(self, markdown: str, config_data: dict[str, Any]) -> dict[str, Any]:
        if not self.lock.acquire(blocking=False):
            raise RenderBusyError("已有文档正在生成，请稍候。")
        try:
            config = config_from_dict(config_data)
            validate_config(config)
            blocks = parse_markdown(markdown)
            renderer = ReportRenderer(config, base_dir=PROJECT_ROOT)
            pages = renderer.render(blocks)

            job_id = secrets.token_hex(8)
            job_root = self.output_root / job_id
            job_root.mkdir(parents=True, exist_ok=False)
            pdf_path = renderer.save_pdf(job_root / "markdown-to-handwrite.pdf")
            preview_urls = []
            for index, page in enumerate(pages, start=1):
                preview = page.convert("RGB")
                preview.thumbnail((1280, 1810), resample=Image.Resampling.LANCZOS)
                preview_name = f"page-{index}.webp"
                preview.save(job_root / preview_name, "WEBP", quality=90, method=4)
                preview_urls.append(f"/output/{job_id}/{preview_name}")
            return {
                "jobId": job_id,
                "pageCount": len(pages),
                "pages": preview_urls,
                "pdf": f"/output/{job_id}/{pdf_path.name}",
            }
        finally:
            self.lock.release()


def _safe_child(root: Path, relative: str) -> Path | None:
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root.resolve())
        return candidate
    except (OSError, ValueError):
        return None


class WebApp:
    def __init__(self, output_root: Path = OUTPUT_ROOT):
        self.render_service = RenderService(output_root)

    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        app = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "HandwrittenReport/0.2"

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                if path == "/api/health":
                    self._send_json({"status": "ok"})
                elif path == "/api/bootstrap":
                    self._send_json(build_bootstrap())
                elif path.startswith("/api/examples/"):
                    self._serve_example(path.removeprefix("/api/examples/"))
                elif path.startswith("/output/"):
                    self._serve_output(path.removeprefix("/output/"))
                else:
                    self._serve_static("index.html" if path in {"/", ""} else path.lstrip("/"))

            def do_POST(self) -> None:  # noqa: N802
                if urlparse(self.path).path != "/api/render":
                    self._send_json({"error": "接口不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    payload = self._read_json()
                    markdown = payload.get("markdown", "")
                    if not isinstance(markdown, str) or not markdown.strip():
                        raise ValueError("请输入要生成的 Markdown 内容。")
                    result = app.render_service.render(markdown, payload.get("config", {}))
                    self._send_json(result)
                except RenderBusyError as error:
                    self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
                except (TypeError, ValueError, KeyError, OSError) as error:
                    self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                except Exception as error:  # pragma: no cover - final HTTP boundary
                    print(f"[web-render-error] {error}")
                    self._send_json({"error": "生成失败，请检查内容、字体和背景配置。"}, HTTPStatus.INTERNAL_SERVER_ERROR)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("请求内容为空或超过 4 MB。")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求必须是 JSON 对象。")
                return payload

            def _serve_example(self, name: str) -> None:
                path = _safe_child(PROJECT_ROOT / "examples", name)
                if path is None or path.suffix.lower() != ".md" or not path.is_file():
                    self._send_json({"error": "示例不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_bytes(path.read_bytes(), "text/markdown; charset=utf-8")

            def _serve_output(self, relative: str) -> None:
                path = _safe_child(app.render_service.output_root, relative)
                if path is None or not path.is_file():
                    self._send_json({"error": "文件不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                headers = {}
                if path.suffix.lower() == ".pdf":
                    headers["Content-Disposition"] = 'attachment; filename="markdown-to-handwrite.pdf"'
                self._send_bytes(path.read_bytes(), content_type, headers)

            def _serve_static(self, relative: str) -> None:
                path = _safe_child(STATIC_ROOT, relative)
                if path is None or not path.is_file():
                    self._send_json({"error": "页面不存在。"}, HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._send_bytes(path.read_bytes(), content_type)

            def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send_bytes(body, "application/json; charset=utf-8", status=status)

            def _send_bytes(
                self,
                body: bytes,
                content_type: str,
                headers: dict[str, str] | None = None,
                status: HTTPStatus = HTTPStatus.OK,
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string: str, *args: object) -> None:
                print(f"[web] {self.address_string()} - {format_string % args}")

        return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the MarkdownToHandwrite WebUI.")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the UI in the default browser.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    app = WebApp()
    server = ThreadingHTTPServer((args.host, args.port), app.handler_class())
    url = f"http://{args.host}:{server.server_port}"
    print(f"MarkdownToHandwrite WebUI: {url}")
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWebUI stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
