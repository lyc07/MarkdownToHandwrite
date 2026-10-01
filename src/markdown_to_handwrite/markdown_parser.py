from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable

from markdown_it import MarkdownIt
from markdown_it.rules_block import html_block

from .latex_text import latex_to_hand_text
from .typography import westernize_punctuation

try:
    from mdit_py_plugins.dollarmath import dollarmath_plugin
except Exception:  # pragma: no cover - optional dependency fallback
    dollarmath_plugin = None


@dataclass
class InlinePart:
    kind: str
    text: str = ""
    src: str = ""
    alt: str = ""


@dataclass
class HeadingBlock:
    level: int
    parts: list[InlinePart]


@dataclass
class ParagraphBlock:
    parts: list[InlinePart]
    no_indent: bool = False


@dataclass
class FormulaBlock:
    text: str


@dataclass
class TableBlock:
    headers: list[list[InlinePart]]
    rows: list[list[list[InlinePart]]]


@dataclass
class ImageBlock:
    alt: str
    src: str


@dataclass
class ListBlock:
    ordered: bool
    items: list[list[InlinePart]]
    start: int = 1


@dataclass
class CodeBlock:
    text: str
    language: str = ""


@dataclass
class RuleBlock:
    pass


@dataclass
class PageBreakBlock:
    pass


Block = HeadingBlock | ParagraphBlock | FormulaBlock | TableBlock | ImageBlock | ListBlock | CodeBlock | RuleBlock | PageBreakBlock


def parse_markdown(source: str) -> list[Block]:
    source = _protect_block_math(source)
    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    parser.block.ruler.before("html_block", "layout_directive", _layout_directive_block_rule, {"alt": ["paragraph", "reference", "blockquote"]})
    parser.block.ruler.at("html_block", _html_block_rule, {"alt": ["paragraph", "reference", "blockquote"]})
    if dollarmath_plugin is not None:
        parser.use(dollarmath_plugin, allow_space=True, allow_digits=True)
    parser.inline.ruler.before("escape", "latex_math_inline", _latex_inline_rule)
    tokens = parser.parse(source)
    blocks: list[Block] = []
    index = 0
    pending_no_indent = False
    while index < len(tokens):
        token = tokens[index]
        if token.type not in {"paragraph_open", "noindent"}:
            pending_no_indent = False
        if token.type == "heading_open":
            level = int(token.tag[1])
            parts = _inline_to_parts(tokens[index + 1])
            blocks.append(HeadingBlock(level=level, parts=parts))
            index += 3
        elif token.type == "paragraph_open":
            parts = _inline_to_parts(tokens[index + 1], block_controls=True)
            pending_no_indent = _append_paragraph_or_images(blocks, parts, no_indent=pending_no_indent)
            index += 3
        elif token.type == "noindent":
            pending_no_indent = True
            index += 1
        elif token.type in {"math_block", "amsmath"}:
            blocks.append(FormulaBlock(token.content.strip()))
            index += 1
        elif token.type in {"fence", "code_block"}:
            blocks.append(CodeBlock(text=token.content.rstrip("\n"), language=token.info.strip()))
            index += 1
        elif token.type == "table_open":
            table, index = _parse_table(tokens, index)
            blocks.append(table)
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            list_block, index = _parse_list(tokens, index)
            blocks.append(list_block)
        elif token.type == "html_block":
            media = _html_media_parts(token.content)
            if media:
                _append_paragraph_or_images(blocks, media)
            else:
                _append_paragraph_or_images(blocks, [InlinePart("text", token.content)])
            index += 1
        elif token.type == "hr":
            blocks.append(RuleBlock())
            index += 1
        elif token.type == "page_break":
            blocks.append(PageBreakBlock())
            index += 1
        else:
            index += 1
    return _restore_block_math(blocks)


def parts_to_text(parts: Iterable[InlinePart]) -> str:
    pieces: list[str] = []
    for part in parts:
        if part.kind == "math":
            pieces.append(latex_to_hand_text(part.text))
        elif part.kind in {"break", "hardbreak"}:
            pieces.append("\n")
        elif part.kind == "code":
            pieces.append(part.text)
        elif part.kind == "image":
            pieces.append(part.alt or part.src)
        else:
            pieces.append(part.text)
    return westernize_punctuation(_normalize_inline("".join(pieces)))


def _inline_to_parts(token, block_controls: bool = False) -> list[InlinePart]:
    parts: list[InlinePart] = []
    children = token.children or []
    if not children and token.content:
        return [InlinePart("text", token.content)]
    for index, child in enumerate(children):
        if child.type == "text":
            parts.append(InlinePart("text", child.content))
        elif child.type == "code_inline":
            parts.append(InlinePart("code", child.content))
        elif child.type == "math_inline":
            parts.append(InlinePart("math", child.content))
        elif child.type == "image":
            parts.append(
                InlinePart(
                    "image",
                    text=child.content or child.attrGet("alt") or "",
                    alt=child.content or child.attrGet("alt") or "",
                    src=child.attrGet("src") or "",
                )
            )
        elif child.type == "softbreak":
            # A source newline next to an HTML layout tag is formatting of the
            # markup, not a second requested line break.
            neighbors = children[max(0, index - 1):index] + children[index + 1:index + 2]
            if any(
                neighbor.type == "html_inline"
                and _html_layout_parts(neighbor.content, block_controls) is not None
                and not re.match(r"</?noindent(?=[\s/>])", neighbor.content, flags=re.I)
                for neighbor in neighbors
            ):
                continue
            parts.append(InlinePart("break"))
        elif child.type == "hardbreak":
            parts.append(InlinePart("hardbreak"))
        elif child.type == "html_inline":
            layout = _html_layout_parts(child.content, block_controls)
            if layout is not None:
                parts.extend(layout)
            else:
                media = _html_media_parts(child.content)
                parts.extend(media or [InlinePart("text", child.content)])
        elif child.children:
            parts.extend(_inline_to_parts(child, block_controls))
    return parts


def _layout_directive_block_rule(state, start_line: int, end_line: int, silent: bool) -> bool:
    if state.is_code_block(start_line):
        return False
    # An unindented tag after a list belongs to the document. An indented tag
    # inside a list item keeps the same literal behavior as its inline form.
    if state.blkIndent and state.sCount[start_line] >= state.blkIndent:
        return False
    start = state.bMarks[start_line] + state.tShift[start_line]
    line = state.src[start:state.eMarks[start_line]].strip()
    match = re.fullmatch(r'''<(newpage|noindent)(?:\s+(?:[^<>"']|"[^"]*"|'[^']*')*)?\s*/?>''', line, flags=re.I)
    if not match:
        return False
    if not silent:
        token = state.push("page_break" if match.group(1).lower() == "newpage" else "noindent", "", 0)
        token.map = [start_line, start_line + 1]
        state.line = start_line + 1
    return True


def _html_block_rule(state, start_line: int, end_line: int, silent: bool) -> bool:
    start = state.bMarks[start_line] + state.tShift[start_line]
    line = state.src[start:state.eMarks[start_line]]
    if re.match(r"</?(?:br|p|newpage|noindent|img)(?=[\s/>])", line, flags=re.I):
        # Let Markdown tokenize controls and images inline so subsequent
        # headings, page breaks, lists, and formulas are still parsed normally.
        return False
    return html_block(state, start_line, end_line, silent)


class _HtmlLayoutParser(HTMLParser):
    def __init__(self, block_controls: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.block_controls = block_controls
        self.recognized = False
        self.parts: list[InlinePart] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.recognized = True
            self.parts.append(InlinePart("hardbreak"))
        elif self.block_controls and tag in {"p", "newpage"}:
            self.recognized = True
            self.parts.append(InlinePart("paragraph_break" if tag == "p" else "page_break"))
        elif self.block_controls and tag == "noindent":
            self.recognized = True
            self.parts.append(InlinePart("noindent"))

    def handle_endtag(self, tag: str) -> None:
        if self.block_controls and tag in {"p", "newpage"}:
            self.recognized = True
            if tag == "p":
                self.parts.append(InlinePart("paragraph_break"))
        elif self.block_controls and tag == "noindent":
            self.recognized = True
            self.parts.append(InlinePart("noindent_end"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def _html_layout_parts(markup: str, block_controls: bool) -> list[InlinePart] | None:
    parser = _HtmlLayoutParser(block_controls)
    parser.feed(markup)
    parser.close()
    return parser.parts if parser.recognized else None


def _latex_inline_rule(state, silent: bool) -> bool:
    """Parse standard LaTeX ``\\(...\\)`` before CommonMark consumes the slashes."""
    if not state.src.startswith(r"\(", state.pos):
        return False
    closing = _find_latex_inline_end(state.src, state.pos + 2, state.posMax)
    if closing < 0:
        return False
    source = state.src[state.pos + 2:closing]
    if not source.strip():
        return False
    if not silent:
        token = state.push("math_inline", "math", 0)
        token.content = source.strip()
        token.markup = r"\("
    state.pos = closing + 2
    return True


def _find_latex_inline_end(text: str, start: int, end: int) -> int:
    depth = 0
    first_grouped_closing = -1
    index = start
    while index < end:
        char = text[index]
        if char == "\\":
            # Skip escaped braces and paired backslashes. A closing marker
            # inside a group such as \text{...} belongs to that group.
            if text.startswith(r"\)", index) and index + 2 <= end:
                if depth == 0:
                    return index
                if first_grouped_closing < 0:
                    first_grouped_closing = index
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        index += 1
    # Preserve the formula renderer's missing-brace diagnostic when the
    # user supplies an outer delimiter but leaves a group unfinished.
    return first_grouped_closing if depth else -1


def _append_paragraph_or_images(
    blocks: list[Block], parts: list[InlinePart], no_indent: bool = False,
) -> bool:
    """Return an unused no-indent directive for the immediately next paragraph."""
    current: list[InlinePart] = []
    for part in parts:
        if part.kind == "noindent":
            no_indent = True
        elif part.kind == "noindent_end":
            continue
        elif part.kind in {"image", "paragraph_break", "page_break"}:
            if _has_text(current):
                blocks.append(ParagraphBlock(current, no_indent=no_indent))
                no_indent = False
            current = []
            if part.kind == "image":
                blocks.append(ImageBlock(alt=part.alt, src=part.src))
                no_indent = False
            elif part.kind == "page_break":
                blocks.append(PageBreakBlock())
                no_indent = False
        else:
            current.append(part)
    if _has_text(current):
        blocks.append(ParagraphBlock(current, no_indent=no_indent))
        no_indent = False
    return no_indent


def _has_text(parts: list[InlinePart]) -> bool:
    return bool(parts_to_text(parts).strip()) or any(part.kind == "hardbreak" for part in parts)


class _HtmlMediaParser(HTMLParser):
    MEDIA_TAGS = {"img", "iframe", "video", "embed", "object"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[InlinePart] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.MEDIA_TAGS:
            return
        values = {name.lower(): value or "" for name, value in attrs}
        src = values.get("src") or values.get("data") or values.get("poster") or ""
        alt = values.get("alt") or values.get("title") or values.get("aria-label") or src or tag
        self.parts.append(InlinePart("image", text=alt, alt=alt, src=src))


def _html_media_parts(markup: str) -> list[InlinePart]:
    parser = _HtmlMediaParser()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        return []
    return parser.parts


def _parse_table(tokens, start: int) -> tuple[TableBlock, int]:
    rows: list[list[list[InlinePart]]] = []
    row: list[list[InlinePart]] | None = None
    cell: list[InlinePart] | None = None
    index = start + 1
    while index < len(tokens) and tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "tr_open":
            row = []
        elif token.type in {"th_open", "td_open"}:
            cell = []
        elif token.type == "inline" and cell is not None:
            cell.extend(_inline_to_parts(token))
        elif token.type in {"th_close", "td_close"}:
            if row is not None and cell is not None:
                row.append(cell)
            cell = None
        elif token.type == "tr_close":
            if row is not None:
                rows.append(row)
            row = None
        index += 1
    headers = rows[0] if rows else []
    body = rows[1:] if len(rows) > 1 else []
    return TableBlock(headers=headers, rows=body), index + 1


def _parse_list(tokens, start: int) -> tuple[ListBlock, int]:
    ordered = tokens[start].type == "ordered_list_open"
    start_number = int(tokens[start].attrGet("start") or 1)
    items: list[list[InlinePart]] = []
    index = start + 1
    while index < len(tokens) and tokens[index].type not in {"bullet_list_close", "ordered_list_close"}:
        if tokens[index].type != "list_item_open":
            index += 1
            continue
        index += 1
        parts: list[InlinePart] = []
        while index < len(tokens) and tokens[index].type != "list_item_close":
            token = tokens[index]
            if token.type == "inline":
                if parts:
                    parts.append(InlinePart("break"))
                parts.extend(_inline_to_parts(token))
            elif token.type in {"fence", "code_block"}:
                if parts:
                    parts.append(InlinePart("break"))
                parts.append(InlinePart("code", token.content.strip()))
            index += 1
        items.append(parts)
        index += 1
    return ListBlock(ordered=ordered, items=items, start=start_number), index + 1


def _normalize_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = text.replace("*", "")
    text = text.replace("`", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _protect_block_math(source: str) -> str:
    def replace(match: re.Match[str]) -> str:
        body = match.group(1).strip()
        return f"\n\n```math-block\n{body}\n```\n\n"

    return re.sub(r"\$\$\s*\n?(.+?)\n?\s*\$\$", replace, source, flags=re.S)


def _restore_block_math(blocks: list[Block]) -> list[Block]:
    restored: list[Block] = []
    for block in blocks:
        if isinstance(block, CodeBlock) and block.language == "math-block":
            restored.append(FormulaBlock(block.text.strip()))
        else:
            restored.append(block)
    return restored
