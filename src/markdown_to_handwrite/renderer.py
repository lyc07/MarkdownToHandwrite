from __future__ import annotations

import sys
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
    ParagraphBlock,
    RuleBlock,
    TableBlock,
    parts_to_text,
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
        self._new_page()

    def render(self, blocks: list[Block]) -> list[Image.Image]:
        for block in blocks:
            if isinstance(block, HeadingBlock):
                self._draw_heading(block)
            elif isinstance(block, ParagraphBlock):
                text = parts_to_text(block.parts)
                if any(part.kind == "math" for part in block.parts):
                    self._draw_rich_paragraph(block.parts)
                else:
                    self._draw_paragraph(text)
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
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = round(size * self.config.layout.first_line_indent_em)
        first = True
        for paragraph in text.split("\n"):
            if not paragraph.strip():
                self.y += gap
                continue
            first_width = self.content_w - indent
            lines = wrap_text(self.engine, paragraph.strip(), size, first_width if first else self.content_w)
            for line_index, line in enumerate(lines):
                self._ensure_space(line_h)
                x = self.margin_left + (indent if first and line_index == 0 else 0)
                width = self.content_w - (indent if first and line_index == 0 else 0)
                justify = self._should_justify_paragraph_line(line, line_index, len(lines), size, width)
                self._paste_text(line, x, self.y, size, width, justify=justify)
                self.y += line_h
            first = False
        self.y += gap

    def _draw_rich_paragraph(self, parts: list[InlinePart]) -> None:
        size = pt_to_px(self.config.handwriting.body_font_pt, self.dpi)
        normal_line_h = round(size * self.config.handwriting.line_spacing)
        gap = mm_to_px(self.config.layout.paragraph_gap_mm, self.dpi)
        indent = round(size * self.config.layout.first_line_indent_em)
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
            self._paste_rich_line(line, x, self.y, width)
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
        raw_lines: list[tuple[int, list[tuple[str, object, int]]]] = []
        current: list[tuple[str, object, int]] = []
        used = 0
        line_index = 0

        def current_width() -> int:
            if line_index == 0 and first_line_width is not None:
                return max(1, first_line_width)
            return max(1, max_width)

        def flush() -> None:
            nonlocal current, used, line_index
            while current and current[-1][0] == "text" and not str(current[-1][1]).strip():
                current.pop()
            if current:
                raw_lines.append((current_width(), current))
                line_index += 1
            current = []
            used = 0

        def add_item(kind: str, value: object, width: int) -> None:
            nonlocal used
            if current and used + width > current_width():
                if kind != "text" or not starts_with_forbidden_line_punctuation(str(value)):
                    flush()
            if kind == "text" and not str(value).strip() and not current:
                return
            current.append((kind, value, width))
            used += width

        for part_index, part in enumerate(parts):
            if part.kind == "break":
                flush()
            elif part.kind == "math":
                try:
                    box = self.formula_renderer.render_inline(
                        part.text,
                        size,
                        max_width,
                        seed_extra=f"{seed_extra}:math:{part_index}",
                    )
                except LatexRenderError as error:
                    self._report_formula_error(part.text, error)
                    box = self.formula_renderer.blank_inline(part.text, size, max_width)
                add_item("math", box, box.width)
            else:
                for unit in _inline_units(westernize_punctuation(part.text)):
                    add_item("text", unit, round(self.engine.measure(unit, size)))
        flush()

        lines: list[_RichLine] = []
        for raw_index, (line_width, raw_line) in enumerate(raw_lines):
            visuals: list[tuple[Image.Image, int]] = []
            text_buffer = ""
            visual_index = 0

            def flush_text() -> None:
                nonlocal text_buffer, visual_index
                if not text_buffer:
                    return
                image = self.engine.render_line(
                    text_buffer.rstrip(),
                    size,
                    line_width,
                    seed_extra=f"{seed_extra}:line:{raw_index}:text:{visual_index}",
                )
                visuals.append((image, round(image.height * 0.76)))
                text_buffer = ""
                visual_index += 1

            for kind, value, _ in raw_line:
                if kind == "text":
                    text_buffer += str(value)
                else:
                    flush_text()
                    box = value
                    visuals.append((box.image, box.baseline))
                    visual_index += 1
            flush_text()
            baseline = max((base for _, base in visuals), default=round(size * 0.76))
            descent = max((image.height - base for image, base in visuals), default=normal_line_h - baseline)
            line_h = max(normal_line_h, baseline + descent)
            lines.append(
                _RichLine(
                    visuals=visuals,
                    width=sum(image.width for image, _ in visuals),
                    height=line_h,
                    baseline=baseline,
                )
            )
        return lines

    def _paste_rich_line(
        self,
        line: _RichLine,
        x: int,
        y: int,
        max_width: int,
        align: str = "left",
    ) -> None:
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
        caption = westernize_punctuation(f"图: {block.alt or block.src or '插图空白'}")
        size = pt_to_px(self.config.handwriting.body_font_pt - 1, self.dpi)
        self._paste_text(caption, x0, y1 + mm_to_px(1.5, self.dpi), size, self.content_w, align="center")
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
        weights = [1.0] * col_count
        for row in [block.headers, *block.rows]:
            for index, cell in enumerate(row[:col_count]):
                weights[index] = max(weights[index], self.engine.measure(parts_to_text(cell), size))
        total = sum(weights) or col_count
        widths = [max(mm_to_px(18, self.dpi), round(self.content_w * weight / total)) for weight in weights]
        delta = self.content_w - sum(widths)
        widths[-1] += delta
        return widths

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
            lines = self._layout_rich_parts(
                cell,
                size,
                max(10, width - 2 * pad),
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
            for line in cells[index]:
                self._paste_rich_line(line, x_positions[index] + pad, y, width - 2 * pad)
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
    ) -> None:
        text = westernize_punctuation(text)
        image = self.engine.render_line(text, size, max_width, seed_extra=f"{len(self.pages)}:{x}:{y}", math=math)
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
        if line_index >= line_count - 1:
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
