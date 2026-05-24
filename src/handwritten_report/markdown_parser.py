from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from markdown_it import MarkdownIt

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


Block = HeadingBlock | ParagraphBlock | FormulaBlock | TableBlock | ImageBlock | ListBlock | CodeBlock | RuleBlock


def parse_markdown(source: str) -> list[Block]:
    source = _protect_block_math(source)
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    if dollarmath_plugin is not None:
        parser.use(dollarmath_plugin, allow_space=True, allow_digits=True)
    tokens = parser.parse(source)
    blocks: list[Block] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            level = int(token.tag[1])
            parts = _inline_to_parts(tokens[index + 1])
            blocks.append(HeadingBlock(level=level, parts=parts))
            index += 3
        elif token.type == "paragraph_open":
            parts = _inline_to_parts(tokens[index + 1])
            _append_paragraph_or_images(blocks, parts)
            index += 3
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
        elif token.type == "hr":
            blocks.append(RuleBlock())
            index += 1
        else:
            index += 1
    return _restore_block_math(blocks)


def parts_to_text(parts: Iterable[InlinePart]) -> str:
    pieces: list[str] = []
    for part in parts:
        if part.kind == "math":
            pieces.append(latex_to_hand_text(part.text))
        elif part.kind == "break":
            pieces.append("\n")
        elif part.kind == "code":
            pieces.append(part.text)
        elif part.kind == "image":
            pieces.append(part.alt or part.src)
        else:
            pieces.append(part.text)
    return westernize_punctuation(_normalize_inline("".join(pieces)))


def _inline_to_parts(token) -> list[InlinePart]:
    parts: list[InlinePart] = []
    children = token.children or []
    if not children and token.content:
        return [InlinePart("text", token.content)]
    for child in children:
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
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append(InlinePart("break"))
        elif child.children:
            parts.extend(_inline_to_parts(child))
    return parts


def _append_paragraph_or_images(blocks: list[Block], parts: list[InlinePart]) -> None:
    current: list[InlinePart] = []
    for part in parts:
        if part.kind == "image":
            if _has_text(current):
                blocks.append(ParagraphBlock(current))
                current = []
            blocks.append(ImageBlock(alt=part.alt, src=part.src))
        else:
            current.append(part)
    if _has_text(current):
        blocks.append(ParagraphBlock(current))


def _has_text(parts: list[InlinePart]) -> bool:
    return bool(parts_to_text(parts).strip())


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
