from __future__ import annotations

import sys
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from reportlab.pdfgen import canvas

try:
    import fitz
except ImportError:  # pragma: no cover - optional until a PDF background is used
    fitz = None

from .config import ReportConfig, color, mm_to_px, pt_to_px
from .handwriting import HandwritingEngine, starts_with_forbidden_line_punctuation, wrap_text
from .math_renderer import FormulaRenderer, LatexRenderError
from .markdown_parser import (
    Block,
    CodeBlock,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
    InlinePart,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    RuleBlock,
    TableBlock,
)
from .typography import westernize_punctuation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKGROUND_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}


@dataclass
class _RichLine:
    visuals: list[tuple[Image.Image, int]]
    width: int
    height: int
    baseline: int
    wrapped: bool = False


class ReportRenderer:
    def __init__(self, config: ReportConfig, base_dir: str | Path = "."):
        self.config = config
        self.base_dir = Path(base_dir)
        self.dpi = config.page.dpi
        self.page_w = mm_to_px(config.page.width_mm, self.dpi)
        self.page_h = mm_to_px(config.page.height_mm, self.dpi)
        self.page_w_pt = config.page.width_mm / 25.4 * 72
        self.page_h_pt = config.page.height_mm / 25.4 * 72
        self.margin_left = mm_to_px(config.page.margin_left_mm, self.dpi)
        self.margin_right = mm_to_px(config.page.margin_right_mm, self.dpi)
        self.margin_top = mm_to_px(config.page.margin_top_mm, self.dpi)
        self.margin_bottom = mm_to_px(config.page.margin_bottom_mm, self.dpi)
        self.content_w = self.page_w - self.margin_left - self.margin_right
        footer_gap = config.layout.footer_gap_mm if config.layout.show_page_numbers else 0
        self.bottom_limit = self.page_h - self.margin_bottom - mm_to_px(footer_gap, self.dpi)
        self.background_path = self._resolve_background_path()
        self.background_pdf = self._open_background_pdf()
        self.engine = HandwritingEngine(
            config.handwriting,
            reference_size_px=pt_to_px(config.handwriting.body_font_pt, self.dpi),
            math_reference_size_px=pt_to_px(config.handwriting.math_font_pt, self.dpi),
        )
        self.formula_renderer = FormulaRenderer(self.engine, seed=config.handwriting.seed)
        self.pages: list[Image.Image] = []
        self.page: Image.Image
        self.draw: ImageDraw.ImageDraw
        self.y = self.margin_top
        self.section_counters = [0, 0, 0, 0, 0, 0]
        self.figure_counter = 0
        self._new_page()

    def render(self, blocks: list[Block]) -> list[Image.Image]:
        page_break_pending = False
        for block in blocks:
            if isinstance(block, PageBreakBlock):
                page_break_pending = True
                continue
            if page_break_pending:
                if self.y > self.margin_top:
                    self._new_page()
                page_break_pending = False
            if isinstance(block, HeadingBlock):
                self._draw_heading(block)
            elif isinstance(block, ParagraphBlock):
                self._draw_rich_paragraph(block.parts, no_indent=block.no_indent)
            elif isinstance(block, FormulaBlock):
                self._draw_formula(block.text)
            elif isinstance(block, TableBlock):
                self._draw_table(block)
            elif isinstance(block, ImageBlock):
                self._draw_image_placeholder(block)
            elif isinstance(block, ListBlock):
                self._draw_list(block)
            elif isinstance(block, CodeBlock):
                self._draw_code(block)
            elif isinstance(block, RuleBlock):
                self._draw_rule()
        if self.config.layout.show_page_numbers:
            self._draw_footers()
        return self.pages

    def save_pdf(self, output_path: str | Path) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output), pagesize=(self.page_w_pt, self.page_h_pt))
        for page in self.pages:
            pdf.drawInlineImage(page.convert("RGB"), 0, 0, width=self.page_w_pt, height=self.page_h_pt)
            pdf.showPage()
        pdf.save()
        return output

    def _new_page(self) -> None:
        self.page = self._make_background()
        self.draw = ImageDraw.Draw(self.page)
        self.pages.append(self.page)
        self.y = self.margin_top

    def _make_background(self) -> Image.Image:
        bg_config = self.config.background
        if self.background_path:
            image = self._read_background_page(len(self.pages))
            return ImageOps.fit(image, (self.page_w, self.page_h), method=Image.Resampling.LANCZOS).convert("RGBA")

        page = Image.new("RGBA", (self.page_w, self.page_h), color(bg_config.paper_color, 255))
        draw = ImageDraw.Draw(page)
        line_color = color(bg_config.line_color, 160)
        style = bg_config.style.lower()
        if style == "lined":
            gap = mm_to_px(bg_config.line_gap_mm, self.dpi)
            for y in range(self.margin_top, self.page_h - self.margin_bottom + 1, gap):
                draw.line((self.margin_left // 2, y, self.page_w - self.margin_right // 2, y), fill=line_color, width=1)
        elif style == "grid":
            gap = mm_to_px(bg_config.grid_size_mm, self.dpi)
            for x in range(self.margin_left // 2, self.page_w - self.margin_right // 2 + 1, gap):
                draw.line((x, self.margin_top // 2, x, self.page_h - self.margin_bottom // 2), fill=line_color, width=1)
            for y in range(self.margin_top // 2, self.page_h - self.margin_bottom // 2 + 1, gap):
                draw.line((self.margin_left // 2, y, self.page_w - self.margin_right // 2, y), fill=line_color, width=1)
        elif style == "dot":
            gap = mm_to_px(bg_config.dot_gap_mm, self.dpi)
            radius = max(1, bg_config.dot_radius_px)
            for x in range(self.margin_left // 2, self.page_w - self.margin_right // 2 + 1, gap):
                for y in range(self.margin_top // 2, self.page_h - self.margin_bottom // 2 + 1, gap):
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=line_color)
        if bg_config.draw_margin_line and style in {"lined", "grid", "dot"}:
            x = self.margin_left - mm_to_px(3.0, self.dpi)
            draw.line((x, self.margin_top // 2, x, self.page_h - self.margin_bottom // 2), fill=color(bg_config.margin_line_color, 150), width=2)
        return page

    def _resolve_background_path(self) -> Path | None:
        configured = self.config.background.image
        if configured:
            path = Path(configured)
            candidates = [path] if path.is_absolute() else [
                self.base_dir / path,
                Path.cwd() / path,
                PROJECT_ROOT / path,
            ]
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()
            raise FileNotFoundError(f"Background file not found: {configured}")
        # Generated paper styles must remain authoritative. Automatic asset
        # discovery is only meaningful when the user explicitly selects the
        # image-backed paper mode.
        if self.config.background.style.lower() != "image" or not self.config.background.auto_discover:
            return None
        checked: set[Path] = set()
        for directory in (
            self.base_dir / "background",
            Path.cwd() / "background",
            PROJECT_ROOT / "background",
        ):
            resolved = directory.resolve()
            if resolved in checked or not resolved.is_dir():
                continue
            checked.add(resolved)
            assets = sorted(
                (item for item in resolved.iterdir() if item.is_file() and item.suffix.lower() in BACKGROUND_EXTENSIONS),
                key=lambda item: item.name.casefold(),
            )
            if assets:
                return assets[0]
        return None

    def _open_background_pdf(self):
        if self.background_path is None or self.background_path.suffix.lower() != ".pdf":
            return None
        if fitz is None:
            raise RuntimeError("PDF backgrounds require PyMuPDF. Install it with: python -m pip install PyMuPDF")
        document = fitz.open(str(self.background_path))
        if document.page_count < 1:
            document.close()
            raise ValueError(f"PDF background has no pages: {self.background_path}")
        return document

    def _read_background_page(self, page_index: int) -> Image.Image:
        if self.background_pdf is None:
            return Image.open(self.background_path).convert("RGB")
        source_page = self.background_pdf.load_page(page_index % self.background_pdf.page_count)
        scale = self.dpi / 72.0
        pixmap = source_page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    def _ensure_space(self, height: int) -> None:
        if self.y + height > self.bottom_limit:
            self._new_page()

    def _draw_heading(self, block: HeadingBlock) -> None:
        level = min(max(block.level, 1), 6)
        parts = list(block.parts)
        if self.config.layout.number_sections and level <= 3:
            parts.insert(0, InlinePart("text", f"{self._next_section_number(level)} "))
        font_pt = {
            1: self.config.handwriting.h1_font_pt,
            2: self.config.handwriting.h2_font_pt,
            3: self.config.handwriting.h3_font_pt,
        }.get(level, self.config.handwriting.body_font_pt)
        size = pt_to_px(font_pt, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        gap_before = mm_to_px(self.config.layout.heading_gap_before_mm if len(self.pages) > 1 or self.y > self.margin_top else 0, self.dpi)
        gap_after = mm_to_px(self.config.layout.heading_gap_after_mm, self.dpi)
        lines = self._layout_rich_parts(
            parts,
            size,
            self.content_w,
            line_h,
            seed_extra=f"heading:{len(self.pages)}:{self.y}",
        )
        total_h = gap_before + sum(line.height for line in lines) + gap_after
        self._ensure_space(total_h)
        self.y += gap_before
        align = "center" if level == 1 else "left"
        for line in lines:
            self._paste_rich_line(line, self.margin_left, self.y, self.content_w, align=align)
            self.y += line.height
        self.y += gap_after

    def _next_section_number(self, level: int) -> str:
        self.section_counters[level - 1] += 1
        for index in range(level, len(self.section_counters)):
            self.section_counters[index] = 0
        return ".".join(str(value) for value in self.section_counters[:level] if value)

    def _draw_paragraph(self, text: str) -> None:
        if not text:
            return
        parts: list[InlinePart] = []
        for index, line in enumerate(text.split("\n")):
            if index:
                parts.append(InlinePart("hardbreak"))
            parts.append(InlinePart("text", line))
        self._draw_rich_paragraph(parts)

    def _draw_rich_paragraph(self, parts: list[InlinePart], no_indent: bool = False) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        normal_line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = 0 if no_indent else min(max(0, self.content_w - 1), round(size * self.config.layout.first_line_indent_em))
        lines = self._layout_rich_parts(
            parts,
            size,
            self.content_w,
            normal_line_h,
            seed_extra=f"paragraph:{len(self.pages)}:{self.y}",
            first_line_width=self.content_w - indent,
        )
        for line_index, line in enumerate(lines):
            is_first = line_index == 0
            x = self.margin_left + (indent if is_first else 0)
            width = self.content_w - (indent if is_first else 0)
            self._ensure_space(line.height)
            self._paste_rich_line(
                line, x, self.y, width,
                justify=self.config.layout.justify_paragraphs and line.wrapped and line.width >= width * 0.78,
            )
            self.y += line.height
        self.y += gap

    def _layout_rich_parts(
        self,
        parts: list[InlinePart],
        size: int,
        max_width: int,
        normal_line_h: int,
        seed_extra: str,
        first_line_width: int | None = None,
    ) -> list[_RichLine]:
        """Lay out mixed handwriting and LaTeX for every inline-capable block."""
        # A group is a word/character/formula together with its closing
        # punctuation. It moves to the next line as a unit whenever possible.
        groups: list[list[tuple[str, object]]] = []
        for part_index, part in enumerate(parts):
            if part.kind in {"break", "hardbreak"}:
                groups.append([(part.kind, "")])
            elif part.kind == "math":
                try:
                    box = self.formula_renderer.render_inline(
                        part.text, size, max(1, max_width),
                        seed_extra=f"{seed_extra}:math:{part_index}",
                    )
                except LatexRenderError as error:
                    self._report_formula_error(part.text, error)
                    box = self.formula_renderer.blank_inline(part.text, size, max(1, max_width))
                groups.append([("math", box)])
            else:
                for unit in _inline_units(westernize_punctuation(part.text)):
                    if starts_with_forbidden_line_punctuation(unit) and groups and groups[-1][0][0] not in {"break", "hardbreak"}:
                        groups[-1].append(("text", unit))
                    else:
                        groups.append([("text", unit)])

        pending = deque(groups)
        lines: list[_RichLine] = []
        measurements: dict[str, float] = {}

        def measure(text: str) -> float:
            if text not in measurements:
                measurements[text] = self.engine.measure(text, size)
            return measurements[text]

        def nominal_width(items: list[tuple[str, object]]) -> float:
            width = 0.0
            buffer = ""
            for kind, value in items:
                if kind == "text":
                    buffer += str(value)
                else:
                    width += measure(buffer) + value.width
                    buffer = ""
            return width + measure(buffer)

        def flatten(selected):
            return [item for group in selected for item in group]

        def whitespace(group) -> bool:
            return all(kind == "text" and not str(value).strip() for kind, value in group)

        while pending:
            line_width = max(1, first_line_width if not lines and first_line_width is not None else max_width)
            selected: list[list[tuple[str, object]]] = []
            while pending:
                group = pending[0]
                if group[0][0] in {"break", "hardbreak"}:
                    break
                if not selected and whitespace(group):
                    pending.popleft()
                    continue
                if selected and nominal_width(flatten([*selected, group])) > line_width:
                    break
                selected.append(pending.popleft())
                if nominal_width(flatten(selected)) > line_width:
                    break
            while selected and whitespace(selected[-1]):
                selected.pop()
            if not selected:
                if pending and pending[0][0][0] in {"break", "hardbreak"}:
                    if pending.popleft()[0][0] == "hardbreak":
                        lines.append(_RichLine([], 0, normal_line_h, round(size * 0.76)))
                continue

            line_seed = f"{seed_extra}:line:{len(lines)}"
            line = self._render_rich_items(flatten(selected), size, line_width, normal_line_h, line_seed)
            # Font overhang, ink perturbations and image padding all contribute
            # to the visible width. Reflow using that width before pasting.
            while line.width > line_width and len(selected) > 1:
                pending.appendleft(selected.pop())
                while selected and whitespace(selected[-1]):
                    pending.appendleft(selected.pop())
                line = self._render_rich_items(flatten(selected), size, line_width, normal_line_h, line_seed)
            if line.width > line_width and all(kind == "text" for kind, _ in selected[0]):
                text = "".join(str(value) for _, value in selected[0])
                # An overlong word must be splittable, including its first line.
                low, high, cut = 1, len(text) - 1, 0
                while low <= high:
                    middle = (low + high) // 2
                    candidate = self._render_rich_items([("text", text[:middle])], size, line_width, normal_line_h, line_seed)
                    if candidate.width <= line_width:
                        cut = middle
                        low = middle + 1
                    else:
                        high = middle - 1
                cut = max(1, cut)
                preferred = cut
                while preferred > 0 and starts_with_forbidden_line_punctuation(text[preferred:]):
                    preferred -= 1
                # A punctuation sequence longer than a whole line is an
                # unavoidable exception to the usual no-leading-punctuation rule.
                cut = preferred or cut
                if cut < len(text):
                    pending.appendleft([("text", text[cut:])])
                    line = self._render_rich_items([("text", text[:cut])], size, line_width, normal_line_h, line_seed)
            if line.width > line_width:
                # A single formula or glyph may exceed even an empty line.
                line = self._fit_rich_line(line, line_width, normal_line_h)
            while pending and whitespace(pending[0]):
                pending.popleft()
            if pending and pending[0][0][0] in {"break", "hardbreak"}:
                pending.popleft()
            else:
                line.wrapped = bool(pending)
            lines.append(line)
        return lines

    def _render_rich_items(
        self, items: list[tuple[str, object]], size: int, max_width: int,
        normal_line_h: int, seed_extra: str,
    ) -> _RichLine:
        visuals: list[tuple[Image.Image, int]] = []
        text_buffer = ""

        def blank_space(text: str) -> None:
            if text:
                width = max(1, math.ceil(self.engine.measure(text, size)))
                visuals.append((Image.new("RGBA", (width, size)), round(size * 0.76)))

        def flush_text() -> None:
            nonlocal text_buffer
            if not text_buffer:
                return
            core = text_buffer.strip()
            if not core:
                blank_space(text_buffer)
            else:
                leading = len(text_buffer) - len(text_buffer.lstrip())
                trailing = len(text_buffer) - len(text_buffer.rstrip())
                blank_space(text_buffer[:leading])
                image, baseline = self.engine.render_line(
                    core, size, max_width,
                    seed_extra=f"{seed_extra}:text:{len(visuals)}", return_baseline=True,
                )
                visuals.append((image, baseline))
                if trailing:
                    blank_space(text_buffer[-trailing:])
            text_buffer = ""

        for kind, value in items:
            if kind == "text":
                text_buffer += str(value)
            else:
                flush_text()
                visuals.append((value.image, value.baseline))
        flush_text()
        baseline = max((base for _, base in visuals), default=round(size * 0.76))
        descent = max((image.height - base for image, base in visuals), default=normal_line_h - baseline)
        return _RichLine(visuals, sum(image.width for image, _ in visuals), max(normal_line_h, baseline + descent), baseline)

    @staticmethod
    def _fit_rich_line(line: _RichLine, width: int, normal_line_h: int) -> _RichLine:
        if len(line.visuals) == 1:
            image = line.visuals[0][0]
        else:
            image = Image.new("RGBA", (line.width, line.height))
            x = 0
            for visual, baseline in line.visuals:
                image.alpha_composite(visual, (x, line.baseline - baseline))
                x += visual.width
        scale = width / line.width
        image = image.resize((width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        baseline = max(1, round(line.baseline * scale))
        return _RichLine([(image, baseline)], width, max(normal_line_h, image.height), baseline)

    def _paste_rich_line(
        self,
        line: _RichLine,
        x: int,
        y: int,
        max_width: int,
        align: str = "left",
        justify: bool = False,
    ) -> None:
        if justify and align == "left" and line.width > 0 and 1.0 < max_width / line.width <= 1.18:
            image = Image.new("RGBA", (line.width, line.height))
            cursor_x = 0
            for visual, baseline in line.visuals:
                image.alpha_composite(visual, (cursor_x, line.baseline - baseline))
                cursor_x += visual.width
            image = image.resize((max_width, line.height), Image.Resampling.BICUBIC)
            self.page.alpha_composite(image, (round(x), round(y)))
            return
        if align == "center":
            x += max(0, (max_width - line.width) // 2)
        elif align == "right":
            x += max(0, max_width - line.width)
        cursor_x = x
        for image, item_baseline in line.visuals:
            self.page.alpha_composite(image, (round(cursor_x), round(y + line.baseline - item_baseline)))
            cursor_x += image.width

    def _render_formula_image(self, text: str, seed_extra: str) -> Image.Image:
        size = pt_to_px(self.config.handwriting.math_font_pt, self.dpi)
        try:
            return self.formula_renderer.render(
                text,
                size,
                self.content_w - mm_to_px(18, self.dpi),
                seed_extra=seed_extra,
            )
        except LatexRenderError as error:
            self._report_formula_error(text, error)
            return self.formula_renderer.blank_display(size)

    def _report_formula_error(self, latex: str, error: LatexRenderError) -> None:
        compact = " ".join(latex.split())
        print(f"[latex-render-error] {compact} ({error})", file=sys.stderr)

    def _formula_height(self, image: Image.Image) -> int:
        gap = mm_to_px(self.config.layout.formula_gap_mm, self.dpi)
        return gap * 2 + image.height

    def _draw_formula(self, text: str, image: Image.Image | None = None) -> None:
        if not text:
            return
        gap = mm_to_px(self.config.layout.formula_gap_mm, self.dpi)
        image = image or self._render_formula_image(text, seed_extra=f"{len(self.pages)}:{self.y}")
        total_h = self._formula_height(image)
        self._ensure_space(total_h)
        self.y += gap
        x = self.margin_left + (self.content_w - image.width) // 2
        self.page.alpha_composite(image, (x, self.y))
        self.y += image.height
        self.y += gap

    def _draw_list(self, block: ListBlock) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        normal_line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = mm_to_px(self.config.layout.list_indent_mm, self.dpi)
        for offset, item in enumerate(block.items):
            prefix = f"{block.start + offset}. " if block.ordered else "- "
            content_x = self.margin_left + indent
            content_width = self.content_w - indent
            lines = self._layout_rich_parts(
                item,
                size,
                content_width,
                normal_line_h,
                seed_extra=f"list:{len(self.pages)}:{self.y}:{offset}",
            )
            if not lines:
                lines = [_RichLine([], 0, normal_line_h, round(size * 0.76))]
            prefix_image = self.engine.render_line(
                prefix,
                size,
                indent,
                seed_extra=f"list-prefix:{len(self.pages)}:{self.y}:{offset}",
            )
            prefix_baseline = round(prefix_image.height * 0.76)
            for line_index, line in enumerate(lines):
                self._ensure_space(line.height)
                if line_index == 0:
                    prefix_x = content_x - prefix_image.width
                    prefix_y = self.y + line.baseline - prefix_baseline
                    self.page.alpha_composite(prefix_image, (round(prefix_x), round(prefix_y)))
                self._paste_rich_line(line, content_x, self.y, content_width)
                self.y += line.height
        self.y += gap

    def _draw_code(self, block: CodeBlock) -> None:
        size = pt_to_px(self.config.handwriting.code_font_pt, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        pad = mm_to_px(2.0, self.dpi)
        lines: list[str] = []
        for raw in westernize_punctuation(block.text).splitlines() or [""]:
            lines.extend(wrap_text(self.engine, raw, size, self.content_w - 2 * pad))
        height = len(lines) * line_h + 2 * pad
        self._ensure_space(height + pad)
        x0 = self.margin_left
        y0 = self.y
        x1 = self.margin_left + self.content_w
        y1 = y0 + height
        self._rough_rect(x0, y0, x1, y1, color(self.config.handwriting.ink_color, 90), width=1)
        self.y += pad
        for line in lines:
            self._paste_text(line, x0 + pad, self.y, size, self.content_w - 2 * pad)
            self.y += line_h
        self.y = y1 + pad

    def _draw_image_placeholder(self, block: ImageBlock) -> None:
        height = mm_to_px(self.config.layout.image_placeholder_height_mm, self.dpi)
        caption_h = mm_to_px(9.0, self.dpi)
        self._ensure_space(height + caption_h)
        x0 = self.margin_left
        y0 = self.y
        x1 = self.margin_left + self.content_w
        y1 = y0 + height
        if self.config.layout.image_placeholder_border:
            self._rough_rect(x0, y0, x1, y1, color(self.config.handwriting.ink_color, 90), width=1)
        self.figure_counter += 1
        title = block.alt or block.src or "插图空白"
        caption = f"图{self.figure_counter}：{title}" if self.config.layout.number_figures else title
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        self._paste_text(
            caption, x0, y1 + mm_to_px(1.5, self.dpi), size, self.content_w,
            align="center", preserve_punctuation=True,
        )
        self.y = y1 + caption_h

    def _draw_table(self, block: TableBlock) -> None:
        if not block.headers and not block.rows:
            return
        self.y += mm_to_px(self.config.layout.table_gap_mm / 2, self.dpi)
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        pad = mm_to_px(self.config.layout.table_cell_padding_mm, self.dpi)
        col_count = max(len(block.headers), *(len(row) for row in block.rows)) if block.rows else len(block.headers)
        widths = self._table_widths(block, col_count, size)
        header_layout = (
            self._table_row_layout(block.headers, widths, size, line_h, pad, "table:header")
            if block.headers
            else None
        )
        header_height = header_layout[1] if header_layout else 0
        if block.headers:
            self._ensure_space(header_height + line_h)
            self._draw_table_row(widths, header_layout, pad, header=True)
        draw_top = not block.headers
        for row_index, row in enumerate(block.rows):
            row_layout = self._table_row_layout(
                row,
                widths,
                size,
                line_h,
                pad,
                f"table:row:{row_index}",
            )
            row_height = row_layout[1]
            if self.y + row_height > self.bottom_limit:
                self._new_page()
                if block.headers:
                    self._draw_table_row(widths, header_layout, pad, header=True)
                draw_top = not block.headers
            self._draw_table_row(widths, row_layout, pad, header=False, draw_top=draw_top)
            draw_top = False
        self.y += mm_to_px(self.config.layout.table_gap_mm, self.dpi)

    def _table_widths(self, block: TableBlock, col_count: int, size: int) -> list[int]:
        if col_count == 0:
            return []
        if self.content_w < col_count:
            raise ValueError("当前页面宽度不足以容纳这么多列，请减少列数或增大页面宽度。")
        pad = max(0, mm_to_px(self.config.layout.table_cell_padding_mm, self.dpi))
        minimum = [1.0 + 2 * pad] * col_count
        preferred = minimum.copy()
        formula_widths: dict[str, int] = {}
        text_widths: dict[str, float] = {}
        # Handwriting rasters retain four transparent pixels on each side;
        # include that footprint so a short header need not wrap by one pixel.
        ink_slack = max(8, math.ceil(size * 0.15))

        def text_width(text: str) -> float:
            if text not in text_widths:
                text_widths[text] = self.engine.measure(text, size) + (ink_slack if text.strip() else 0)
            return text_widths[text]

        def formula_width(latex: str) -> int:
            if latex not in formula_widths:
                # Measuring must not advance the live renderer's geometry or
                # ink RNGs. A fixed per-formula seed also makes column order
                # irrelevant to the width estimate.
                probe = FormulaRenderer(self.engine, seed=f"{self.config.handwriting.seed}:table:{latex}")
                try:
                    box = probe.render_inline(latex, size, self.content_w, seed_extra="table:measure")
                except LatexRenderError:
                    # The actual cell render reports the error once.
                    box = probe.blank_inline(latex, size, self.content_w)
                formula_widths[latex] = box.width
            return formula_widths[latex]

        for row in [block.headers, *block.rows]:
            for index, cell in enumerate(row[:col_count]):
                line_width = 0.0
                text_buffer = ""

                def flush_text() -> None:
                    nonlocal text_buffer, line_width
                    if text_buffer:
                        line_width += text_width(text_buffer)
                        for unit in _inline_units(text_buffer):
                            if unit.strip():
                                minimum[index] = max(minimum[index], text_width(unit) + 2 * pad)
                        text_buffer = ""

                for part in cell:
                    if part.kind in {"break", "hardbreak"}:
                        flush_text()
                        preferred[index] = max(preferred[index], line_width + 2 * pad)
                        line_width = 0.0
                    elif part.kind == "math":
                        flush_text()
                        width = formula_width(part.text)
                        line_width += width
                        minimum[index] = max(minimum[index], width + 2 * pad)
                    else:
                        text_buffer += westernize_punctuation(part.text)
                flush_text()
                preferred[index] = max(preferred[index], line_width + 2 * pad)

        # Demands wider than the whole table cannot be satisfied without
        # wrapping or scaling, and must not dominate the other columns.
        preferred = [min(self.content_w, max(want, need)) for want, need in zip(preferred, minimum)]
        minimum = [min(need, want) for need, want in zip(minimum, preferred)]
        base = mm_to_px(18, self.dpi)
        if base * col_count > self.content_w:
            base = max(1.0, self.content_w / (2 * col_count))
        widths = [min(float(base), want) for want in preferred]
        remaining = self.content_w - sum(widths)

        def grow_towards(targets: list[float]) -> None:
            nonlocal remaining
            active = [i for i in range(col_count) if targets[i] > widths[i] + 1e-9]
            while active and remaining > 1e-9:
                step = min(remaining / len(active), min(targets[i] - widths[i] for i in active))
                for i in active:
                    widths[i] += step
                remaining = max(0.0, remaining - step * len(active))
                active = [i for i in active if targets[i] > widths[i] + 1e-9]

        # Equal increments with satisfied columns frozen protect short fields
        # and formulas before spending the remaining room on long paragraphs.
        grow_towards(minimum)
        grow_towards(preferred)
        widths = [width + remaining / col_count for width in widths]
        rounded = [max(1, math.floor(width)) for width in widths]
        remainder = self.content_w - sum(rounded)
        order = sorted(range(col_count), key=lambda i: widths[i] - rounded[i], reverse=True)
        for i in order[:remainder]:
            rounded[i] += 1
        return rounded

    def _table_content_geometry(self, width: int, pad: int) -> tuple[int, int]:
        # Narrow tables sacrifice horizontal padding before squeezing their
        # content below one em. Layout and pasting must use the same budget.
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        horizontal_pad = min(max(0, pad), max(0, (width - min(width, size)) // 2))
        return horizontal_pad, max(1, width - 2 * horizontal_pad)

    def _table_row_layout(
        self,
        row: list[list[InlinePart]],
        widths: list[int],
        size: int,
        line_h: int,
        pad: int,
        seed_extra: str,
    ) -> tuple[list[list[_RichLine]], int]:
        cells: list[list[_RichLine]] = []
        content_height = line_h
        for index, width in enumerate(widths):
            cell = row[index] if index < len(row) else []
            _, available = self._table_content_geometry(width, pad)
            lines = self._layout_rich_parts(
                cell,
                size,
                available,
                line_h,
                seed_extra=f"{seed_extra}:cell:{index}",
            )
            cells.append(lines)
            content_height = max(content_height, sum(line.height for line in lines))
        return cells, content_height + 2 * pad

    def _draw_table_row(
        self,
        widths: list[int],
        layout: tuple[list[list[_RichLine]], int],
        pad: int,
        header: bool,
        draw_top: bool = True,
    ) -> None:
        cells, height = layout
        x_positions = [self.margin_left]
        for width in widths:
            x_positions.append(x_positions[-1] + width)
        y0 = self.y
        y1 = self.y + height
        ink = color(self.config.handwriting.ink_color, 200 if header else 170)
        if draw_top:
            self._rough_line(x_positions[0], y0, x_positions[-1], y0, ink, width=2 if header else 1)
        self._rough_line(x_positions[0], y1, x_positions[-1], y1, ink, width=1)
        for x in x_positions:
            self._rough_line(x, y0, x, y1, ink, width=1)
        for index, width in enumerate(widths):
            y = y0 + pad
            horizontal_pad, available = self._table_content_geometry(width, pad)
            for line in cells[index]:
                self._paste_rich_line(line, x_positions[index] + horizontal_pad, y, available)
                y += line.height
        self.y = y1

    def _draw_rule(self) -> None:
        gap = mm_to_px(4.0, self.dpi)
        self._ensure_space(gap)
        self.y += gap

    def _paste_text(
        self,
        text: str,
        x: int,
        y: int,
        size: int,
        max_width: int,
        align: str = "left",
        math: bool = False,
        justify: bool = False,
        preserve_punctuation: bool = False,
    ) -> None:
        if not preserve_punctuation:
            text = westernize_punctuation(text)
        image = self.engine.render_line(text, size, max_width, seed_extra=f"{len(self.pages)}:{x}:{y}", math=math)
        if image.width > max_width:
            scale = max_width / image.width
            image = image.resize((max_width, max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        if justify and align == "left" and image.width > 1:
            stretch = max_width / image.width
            if 1.0 < stretch <= 1.18:
                image = image.resize((max_width, image.height), Image.Resampling.BICUBIC)
        if align == "center":
            x = x + max(0, (max_width - image.width) // 2)
        elif align == "right":
            x = x + max(0, max_width - image.width)
        self.page.alpha_composite(image, (round(x), round(y)))

    def _should_justify_paragraph_line(
        self,
        line: str,
        line_index: int,
        line_count: int,
        size: int,
        width: int,
    ) -> bool:
        if not self.config.layout.justify_paragraphs or line_index >= line_count - 1:
            return False
        measured = self.engine.measure(line, size)
        return measured >= width * 0.78

    def _rough_line(self, x0: int, y0: int, x1: int, y1: int, fill: tuple[int, ...], width: int = 1) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        if y0 == y1:
            self.formula_renderer.draw_horizontal_rule(
                self.page,
                x0,
                y0,
                x1,
                size,
                width=width,
                fill=fill,
                anchor_ends=True,
                variation_scale=0.7,
            )
            return
        self.formula_renderer.draw_rule(
            self.page,
            x0,
            y0,
            x1,
            y1,
            size,
            width=width,
            fill=fill,
            anchor_ends=True,
            variation_scale=0.7,
        )

    def _rough_rect(self, x0: int, y0: int, x1: int, y1: int, fill: tuple[int, ...], width: int = 1) -> None:
        self._rough_line(x0, y0, x1, y0, fill, width)
        self._rough_line(x1, y0, x1, y1, fill, width)
        self._rough_line(x1, y1, x0, y1, fill, width)
        self._rough_line(x0, y1, x0, y0, fill, width)

    def _draw_footers(self) -> None:
        size = pt_to_px(9.5, self.dpi)
        footer_y = self.page_h - mm_to_px(self.config.page.margin_bottom_mm / 2 + 2, self.dpi)
        for index, page in enumerate(self.pages, start=1):
            self.page = page
            label = f"- {index} -"
            image = self.engine.render_line(label, size, self.content_w, seed_extra=f"footer-{index}")
            x = (self.page_w - image.width) // 2
            page.alpha_composite(image, (x, footer_y))


def _inline_units(text: str) -> list[str]:
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
