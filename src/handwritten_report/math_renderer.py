from __future__ import annotations

import random
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .handwriting import HandwritingEngine
from .typography import westernize_punctuation

COMMAND_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "theta": "θ",
    "vartheta": "ϑ",
    "eta": "η",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "varphi": "ϕ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "sum": "∑",
    "prod": "∏",
    "int": "∫",
    "iint": "∬",
    "iiint": "∭",
    "oint": "∮",
    "times": "×",
    "cdot": "·",
    "div": "÷",
    "ast": "*",
    "le": "≤",
    "leq": "≤",
    "ge": "≥",
    "geq": "≥",
    "ne": "≠",
    "neq": "≠",
    "approx": "≈",
    "equiv": "≡",
    "propto": "∝",
    "ll": "≪",
    "gg": "≫",
    "pm": "±",
    "mp": "∓",
    "infty": "∞",
    "infin": "∞",
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "subseteq": "⊆",
    "supset": "⊃",
    "supseteq": "⊇",
    "cup": "∪",
    "cap": "∩",
    "emptyset": "∅",
    "varnothing": "∅",
    "setminus": "∖",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "land": "∧",
    "lor": "∨",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "leftrightarrow": "↔",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "Leftrightarrow": "⇔",
    "mapsto": "↦",
    "partial": "∂",
    "nabla": "∇",
    "degree": "°",
    "circ": "°",
    "sim": "~",
    "perp": "⊥",
    "parallel": "∥",
    "angle": "∠",
    "mid": "|",
    "vert": "|",
    "lvert": "|",
    "rvert": "|",
    "Vert": "||",
    "lVert": "||",
    "rVert": "||",
    "langle": "<",
    "rangle": ">",
    "lfloor": "⌊",
    "rfloor": "⌋",
    "lceil": "⌈",
    "rceil": "⌉",
    "ldots": "...",
    "cdots": "...",
    "dots": "...",
}
COMMAND_TEXT = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "ln", "log", "lg", "exp", "lim", "max", "min",
    "sup", "inf", "det", "dim", "ker", "arg", "gcd",
}
GRID_ENVIRONMENTS = {
    "matrix": ("", ""),
    "pmatrix": ("(", ")"),
    "bmatrix": ("[", "]"),
    "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"),
    "Vmatrix": ("||", "||"),
    "cases": ("{", ""),
}


class LatexRenderError(ValueError):
    pass


@dataclass(frozen=True)
class TextNode:
    text: str


@dataclass(frozen=True)
class SpaceNode:
    factor: float


@dataclass(frozen=True)
class IgnoreNode:
    pass


@dataclass(frozen=True)
class RowNode:
    items: list["MathNode"]


@dataclass(frozen=True)
class FractionNode:
    numerator: "MathNode"
    denominator: "MathNode"


@dataclass(frozen=True)
class RootNode:
    body: "MathNode"
    index: "MathNode | None" = None


@dataclass(frozen=True)
class ScriptNode:
    base: "MathNode"
    superscript: "MathNode | None" = None
    subscript: "MathNode | None" = None


@dataclass(frozen=True)
class AccentNode:
    body: "MathNode"
    kind: str


@dataclass(frozen=True)
class BinomialNode:
    upper: "MathNode"
    lower: "MathNode"


@dataclass(frozen=True)
class MatrixNode:
    rows: list[list["MathNode"]]
    left: str = ""
    right: str = ""


MathNode = TextNode | SpaceNode | IgnoreNode | RowNode | FractionNode | RootNode | ScriptNode | AccentNode | BinomialNode | MatrixNode


@dataclass
class MathBox:
    image: Image.Image
    baseline: int

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


class LatexMathParser:
    def __init__(self, source: str):
        self.source = source
        self.index = 0

    def parse(self) -> MathNode:
        result = self._parse_row()
        if self.index != len(self.source):
            raise LatexRenderError(f"Unexpected token {self.source[self.index]!r} at position {self.index}.")
        return result

    def _parse_row(self, stop: str | None = None) -> MathNode:
        items: list[MathNode] = []
        text: list[str] = []

        def flush_text() -> None:
            if text:
                items.append(TextNode("".join(text)))
                text.clear()

        while self.index < len(self.source):
            char = self.source[self.index]
            if stop and char == stop:
                break
            if char == "}":
                break
            if char == "{":
                flush_text()
                self.index += 1
                group = self._parse_row(stop="}")
                if self.index >= len(self.source) or self.source[self.index] != "}":
                    raise LatexRenderError("Missing closing brace.")
                self.index += 1
                items.append(group)
            elif char == "\\":
                flush_text()
                command_node = self._parse_command()
                if not isinstance(command_node, IgnoreNode):
                    items.append(command_node)
            elif char in "^_":
                flush_text()
                self.index += 1
                argument = self._parse_argument()
                base = items.pop() if items else TextNode("")
                if isinstance(base, TextNode) and len(base.text) > 1:
                    items.append(TextNode(base.text[:-1]))
                    base = TextNode(base.text[-1])
                if isinstance(base, ScriptNode):
                    if char == "^":
                        base = ScriptNode(base.base, argument, base.subscript)
                    else:
                        base = ScriptNode(base.base, base.superscript, argument)
                elif char == "^":
                    base = ScriptNode(base, superscript=argument)
                else:
                    base = ScriptNode(base, subscript=argument)
                items.append(base)
            elif char == "&":
                flush_text()
                self.index += 1
            elif char.isspace():
                flush_text()
                while self.index < len(self.source) and self.source[self.index].isspace():
                    self.index += 1
                items.append(SpaceNode(0.24))
            else:
                text.append(char)
                self.index += 1
        flush_text()
        return RowNode(items)

    def _parse_argument(self) -> MathNode:
        while self.index < len(self.source) and self.source[self.index].isspace():
            self.index += 1
        if self.index >= len(self.source):
            raise LatexRenderError("Missing command argument.")
        if self.source[self.index] == "{":
            self.index += 1
            argument = self._parse_row(stop="}")
            if self.index >= len(self.source) or self.source[self.index] != "}":
                raise LatexRenderError("Missing closing brace.")
            self.index += 1
            return argument
        if self.source[self.index] == "\\":
            return self._parse_command()
        char = self.source[self.index]
        self.index += 1
        return TextNode(char)

    def _parse_command(self) -> MathNode:
        self.index += 1
        if self.index >= len(self.source):
            raise LatexRenderError("Trailing backslash.")
        if not self.source[self.index].isalpha():
            symbol = self.source[self.index]
            self.index += 1
            if symbol in {",", ";", "!", ":"}:
                return SpaceNode({",": 0.16, ";": 0.28, "!": -0.08, ":": 0.2}[symbol])
            if symbol == "\\":
                return SpaceNode(0.3)
            return TextNode(symbol)
        start = self.index
        while self.index < len(self.source) and self.source[self.index].isalpha():
            self.index += 1
        command = self.source[start:self.index]
        if command in {"frac", "dfrac", "tfrac"}:
            return FractionNode(self._parse_argument(), self._parse_argument())
        if command == "binom":
            return BinomialNode(self._parse_argument(), self._parse_argument())
        if command == "sqrt":
            index = None
            if self.index < len(self.source) and self.source[self.index] == "[":
                index = LatexMathParser(self._read_bracketed()).parse()
            return RootNode(self._parse_argument(), index)
        if command in {"bar", "overline", "underline", "vec", "hat", "widehat", "tilde", "widetilde", "dot", "ddot"}:
            return AccentNode(self._parse_argument(), command)
        if command in {"overset", "stackrel"}:
            upper = self._parse_argument()
            return ScriptNode(self._parse_argument(), superscript=upper)
        if command == "underset":
            lower = self._parse_argument()
            return ScriptNode(self._parse_argument(), subscript=lower)
        if command == "begin":
            environment = self._read_group_text()
            if environment not in GRID_ENVIRONMENTS:
                raise LatexRenderError(f"Unsupported environment: {environment}")
            end_marker = rf"\end{{{environment}}}"
            end = self.source.find(end_marker, self.index)
            if end < 0:
                raise LatexRenderError(f"Missing {end_marker}.")
            body = self.source[self.index:end]
            self.index = end + len(end_marker)
            left, right = GRID_ENVIRONMENTS[environment]
            return MatrixNode(_parse_grid_body(body), left, right)
        if command in {"limits", "nolimits"}:
            return IgnoreNode()
        if command in {"left", "right", "displaystyle", "textstyle", "scriptstyle"}:
            return SpaceNode(0)
        if command in {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr"}:
            return SpaceNode(0)
        if command in {"quad", "qquad"}:
            return SpaceNode(1.0 if command == "quad" else 2.0)
        if command in COMMAND_SYMBOLS:
            return TextNode(COMMAND_SYMBOLS[command])
        if command in COMMAND_TEXT:
            return TextNode(command)
        if command in {"mathrm", "mathbf", "mathit", "operatorname", "text"}:
            return self._parse_argument()
        raise LatexRenderError(f"Unsupported command: \\{command}")

    def _read_bracketed(self) -> str:
        if self.index >= len(self.source) or self.source[self.index] != "[":
            raise LatexRenderError("Missing opening bracket.")
        start = self.index + 1
        depth = 1
        self.index += 1
        while self.index < len(self.source) and depth:
            if self.source[self.index] == "[":
                depth += 1
            elif self.source[self.index] == "]":
                depth -= 1
            self.index += 1
        if depth:
            raise LatexRenderError("Missing closing bracket.")
        return self.source[start:self.index - 1]

    def _read_group_text(self) -> str:
        while self.index < len(self.source) and self.source[self.index].isspace():
            self.index += 1
        if self.index >= len(self.source) or self.source[self.index] != "{":
            raise LatexRenderError("Expected braced environment name.")
        start = self.index + 1
        end = self.source.find("}", start)
        if end < 0:
            raise LatexRenderError("Missing closing brace.")
        self.index = end + 1
        return self.source[start:end]


class FormulaRenderer:
    """Two-dimensional math compositor inspired by hfmath's box-layout pipeline."""

    def __init__(self, engine: HandwritingEngine, seed: object = None):
        self.engine = engine
        self.random = random.Random(str(seed))

    def render(self, latex: str, size_px: int, max_width: int, seed_extra: str = "") -> Image.Image:
        latex = westernize_punctuation(latex)
        line_boxes = [
            self._layout(LatexMathParser(line).parse(), size_px, f"{seed_extra}:{index}")
            for index, line in enumerate(_formula_lines(latex))
            if line.strip()
        ]
        if not line_boxes:
            return Image.new("RGBA", (1, size_px), (0, 0, 0, 0))
        gap = max(4, round(size_px * 0.4))
        width = max(box.width for box in line_boxes)
        height = sum(box.height for box in line_boxes) + gap * (len(line_boxes) - 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for box in line_boxes:
            image.alpha_composite(box.image, ((width - box.width) // 2, y))
            y += box.height + gap
        if image.width > max_width:
            scale = max_width / image.width
            height = max(1, round(image.height * scale))
            image = image.resize((max_width, height), Image.Resampling.LANCZOS)
        return image

    def render_inline(self, latex: str, size_px: int, max_width: int, seed_extra: str = "") -> MathBox:
        latex = westernize_punctuation(latex)
        lines = _formula_lines(latex)
        if len(lines) != 1:
            image = self.render(latex, size_px, max_width, seed_extra)
            return MathBox(image, round(image.height * 0.72))
        box = self._layout(LatexMathParser(lines[0]).parse(), size_px, seed_extra)
        if box.width <= max_width:
            return box
        scale = max_width / box.width
        image = box.image.resize((max_width, max(1, round(box.height * scale))), Image.Resampling.LANCZOS)
        return MathBox(image, max(1, round(box.baseline * scale)))

    def blank_display(self, size_px: int) -> Image.Image:
        return Image.new("RGBA", (1, max(1, round(size_px * 1.25))), (0, 0, 0, 0))

    def blank_inline(self, latex: str, size_px: int, max_width: int) -> MathBox:
        width = min(max_width, max(size_px, round(size_px * min(8.0, max(1.5, len(latex) * 0.22)))))
        image = Image.new("RGBA", (width, max(1, round(size_px * 1.1))), (0, 0, 0, 0))
        return MathBox(image, round(size_px * 0.76))

    def _layout(self, node: MathNode, size_px: int, seed_extra: str) -> MathBox:
        if isinstance(node, TextNode):
            return self._text_box(node.text, size_px, seed_extra)
        if isinstance(node, SpaceNode):
            width = max(0, round(size_px * node.factor))
            return MathBox(Image.new("RGBA", (max(1, width), size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        if isinstance(node, IgnoreNode):
            return MathBox(Image.new("RGBA", (1, size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        if isinstance(node, RowNode):
            boxes = [
                self._layout(child, size_px, f"{seed_extra}:row:{index}")
                for index, child in enumerate(node.items)
            ]
            return self._row_box(boxes, size_px)
        if isinstance(node, FractionNode):
            return self._fraction_box(node, size_px, seed_extra)
        if isinstance(node, RootNode):
            return self._root_box(node, size_px, seed_extra)
        if isinstance(node, ScriptNode):
            return self._script_box(node, size_px, seed_extra)
        if isinstance(node, BinomialNode):
            return self._binomial_box(node, size_px, seed_extra)
        if isinstance(node, MatrixNode):
            return self._matrix_box(node, size_px, seed_extra)
        return self._accent_box(node, size_px, seed_extra)

    def _text_box(self, text: str, size_px: int, seed_extra: str) -> MathBox:
        if not text:
            return MathBox(Image.new("RGBA", (1, size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        width = max(16, round(self.engine.measure(text, size_px, math=True) + 2 * size_px))
        image = self.engine.render_line(text, size_px, width, seed_extra=seed_extra, math=True)
        return MathBox(image, max(1, round(image.height * 0.76)))

    def _row_box(self, boxes: list[MathBox], size_px: int) -> MathBox:
        if not boxes:
            return MathBox(Image.new("RGBA", (1, size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        baseline = max(box.baseline for box in boxes)
        descent = max(box.height - box.baseline for box in boxes)
        spacing = max(1, round(size_px * 0.04))
        width = sum(box.width for box in boxes) + spacing * (len(boxes) - 1)
        image = Image.new("RGBA", (max(1, width), max(1, baseline + descent)), (0, 0, 0, 0))
        x = 0
        for box in boxes:
            image.alpha_composite(box.image, (x, baseline - box.baseline))
            x += box.width + spacing
        return MathBox(image, baseline)

    def _fraction_box(self, node: FractionNode, size_px: int, seed_extra: str) -> MathBox:
        child_size = max(10, round(size_px * 0.78))
        numerator = self._layout(node.numerator, child_size, f"{seed_extra}:num")
        denominator = self._layout(node.denominator, child_size, f"{seed_extra}:den")
        pad = max(4, round(size_px * 0.18))
        gap = max(3, round(size_px * 0.13))
        stroke = max(1, round(size_px / 18))
        width = max(numerator.width, denominator.width) + 2 * pad
        bar_y = numerator.height + gap
        height = bar_y + stroke + gap + denominator.height
        baseline = min(height - 1, bar_y + stroke + round(size_px * 0.28))
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        image.alpha_composite(numerator.image, ((width - numerator.width) // 2, 0))
        image.alpha_composite(denominator.image, ((width - denominator.width) // 2, bar_y + stroke + gap))
        self._rough_line(image, pad // 2, bar_y, width - pad // 2, bar_y, stroke)
        return MathBox(image, baseline)

    def _root_box(self, node: RootNode, size_px: int, seed_extra: str) -> MathBox:
        body = self._layout(node.body, size_px, f"{seed_extra}:body")
        radical = self._text_box("√", max(10, round(size_px * 1.08)), f"{seed_extra}:radical")
        index = self._layout(node.index, max(8, round(size_px * 0.48)), f"{seed_extra}:index") if node.index else None
        top_gap = max(3, round(size_px * 0.12))
        overlap = max(1, round(size_px * 0.1))
        prefix_w = max(0, (index.width - round(radical.width * 0.3)) if index else 0)
        body_x = prefix_w + radical.width - overlap
        width = body_x + body.width + top_gap
        baseline = top_gap + body.baseline
        radical_y = max(0, baseline - radical.baseline)
        height = max(top_gap + body.height, radical_y + radical.height, index.height if index else 0)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if index:
            image.alpha_composite(index.image, (0, 0))
        image.alpha_composite(radical.image, (prefix_w, radical_y))
        image.alpha_composite(body.image, (body_x, top_gap))
        self._rough_line(image, body_x, top_gap, width - 1, top_gap, max(1, round(size_px / 20)))
        return MathBox(image, baseline)

    def _script_box(self, node: ScriptNode, size_px: int, seed_extra: str) -> MathBox:
        base = self._layout(node.base, size_px, f"{seed_extra}:base")
        script_size = max(9, round(size_px * 0.58))
        superscript = self._layout(node.superscript, script_size, f"{seed_extra}:sup") if node.superscript else None
        subscript = self._layout(node.subscript, script_size, f"{seed_extra}:sub") if node.subscript else None
        raise_by = round(size_px * 0.34)
        lower_by = round(size_px * 0.23)
        initial_sup_y = base.baseline - raise_by - superscript.baseline if superscript else 0
        base_y = max(0, -initial_sup_y)
        baseline = base_y + base.baseline
        script_x = max(1, base.width - round(size_px * 0.09))
        sup_y = base_y + initial_sup_y
        sub_y = baseline + lower_by - subscript.baseline if subscript else 0
        height = base_y + base.height
        if superscript:
            height = max(height, superscript.height)
        if subscript:
            height = max(height, sub_y + subscript.height)
        width = base.width + max(
            superscript.width if superscript else 0,
            subscript.width if subscript else 0,
        )
        image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
        image.alpha_composite(base.image, (0, base_y))
        if superscript:
            image.alpha_composite(superscript.image, (script_x, sup_y))
        if subscript:
            image.alpha_composite(subscript.image, (script_x, sub_y))
        return MathBox(image, baseline)

    def _accent_box(self, node: AccentNode, size_px: int, seed_extra: str) -> MathBox:
        body = self._layout(node.body, size_px, f"{seed_extra}:body")
        accent_h = max(4, round(size_px * 0.2))
        if node.kind == "underline":
            image = Image.new("RGBA", (body.width + 2, body.height + accent_h), (0, 0, 0, 0))
            image.alpha_composite(body.image, (1, 0))
            self._rough_line(image, 2, body.height + 1, body.width, body.height + 1, max(1, round(size_px / 20)))
            return MathBox(image, body.baseline)
        image = Image.new("RGBA", (body.width + 2, body.height + accent_h), (0, 0, 0, 0))
        image.alpha_composite(body.image, (1, accent_h))
        stroke = max(1, round(size_px / 20))
        if node.kind in {"dot", "ddot"}:
            radius = max(1, round(size_px * 0.04))
            centers = [body.width // 2] if node.kind == "dot" else [body.width // 2 - radius * 2, body.width // 2 + radius * 2]
            draw = ImageDraw.Draw(image)
            for center in centers:
                draw.ellipse((center - radius, 1, center + radius, 1 + 2 * radius), fill=self.engine.ink)
        elif node.kind in {"hat", "widehat"}:
            mid = body.width // 2
            self._rough_line(image, 2, accent_h - 2, mid, 1, stroke)
            self._rough_line(image, mid, 1, body.width, accent_h - 2, stroke)
        elif node.kind in {"tilde", "widetilde"}:
            draw = ImageDraw.Draw(image)
            draw.line([(2, accent_h - 2), (body.width // 3, 1), (2 * body.width // 3, accent_h - 2), (body.width, 1)], fill=self.engine.ink, width=stroke)
        else:
            self._rough_line(image, 2, accent_h - 2, body.width, accent_h - 2, stroke)
        if node.kind == "vec":
            self._rough_line(
                image,
                body.width - round(size_px * 0.16),
                accent_h - round(size_px * 0.13),
                body.width,
                accent_h - 2,
                max(1, round(size_px / 22)),
            )
        return MathBox(image, body.baseline + accent_h)

    def _binomial_box(self, node: BinomialNode, size_px: int, seed_extra: str) -> MathBox:
        stack = self._stack_box(
            [node.upper, node.lower],
            max(10, round(size_px * 0.76)),
            f"{seed_extra}:binom",
        )
        return self._delimit_box(stack, "(", ")", size_px, seed_extra)

    def _matrix_box(self, node: MatrixNode, size_px: int, seed_extra: str) -> MathBox:
        if not node.rows:
            return self._text_box("", size_px, seed_extra)
        cell_size = max(10, round(size_px * 0.82))
        rows = [
            [self._layout(cell, cell_size, f"{seed_extra}:cell:{row_index}:{column_index}") for column_index, cell in enumerate(row)]
            for row_index, row in enumerate(node.rows)
        ]
        columns = max(len(row) for row in rows)
        column_widths = [
            max((row[column].width for row in rows if column < len(row)), default=1)
            for column in range(columns)
        ]
        col_gap = max(6, round(size_px * 0.34))
        row_gap = max(5, round(size_px * 0.26))
        row_metrics: list[tuple[int, int]] = []
        for row in rows:
            baseline = max((cell.baseline for cell in row), default=cell_size)
            descent = max((cell.height - cell.baseline for cell in row), default=0)
            row_metrics.append((baseline, descent))
        width = sum(column_widths) + col_gap * (columns - 1)
        height = sum(baseline + descent for baseline, descent in row_metrics) + row_gap * (len(rows) - 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for row, (baseline, descent) in zip(rows, row_metrics):
            x = 0
            for column, cell in enumerate(row):
                image.alpha_composite(cell.image, (x + (column_widths[column] - cell.width) // 2, y + baseline - cell.baseline))
                x += column_widths[column] + col_gap
            y += baseline + descent + row_gap
        grid = MathBox(image, height // 2)
        return self._delimit_box(grid, node.left, node.right, size_px, seed_extra)

    def _stack_box(self, items: list[MathNode], size_px: int, seed_extra: str) -> MathBox:
        boxes = [self._layout(item, size_px, f"{seed_extra}:{index}") for index, item in enumerate(items)]
        gap = max(4, round(size_px * 0.18))
        width = max(box.width for box in boxes)
        height = sum(box.height for box in boxes) + gap * (len(boxes) - 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for box in boxes:
            image.alpha_composite(box.image, ((width - box.width) // 2, y))
            y += box.height + gap
        return MathBox(image, height // 2)

    def _delimit_box(self, body: MathBox, left: str, right: str, size_px: int, seed_extra: str) -> MathBox:
        delimiter_size = max(size_px, round(body.height * 0.86))
        left_box = self._text_box(left, delimiter_size, f"{seed_extra}:left") if left else None
        right_box = self._text_box(right, delimiter_size, f"{seed_extra}:right") if right else None
        gap = max(2, round(size_px * 0.08))
        width = body.width
        if left_box:
            width += left_box.width + gap
        if right_box:
            width += right_box.width + gap
        height = max(body.height, left_box.height if left_box else 0, right_box.height if right_box else 0)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        x = 0
        if left_box:
            image.alpha_composite(left_box.image, (0, (height - left_box.height) // 2))
            x += left_box.width + gap
        image.alpha_composite(body.image, (x, (height - body.height) // 2))
        x += body.width + gap
        if right_box:
            image.alpha_composite(right_box.image, (x, (height - right_box.height) // 2))
        return MathBox(image, (height - body.height) // 2 + body.baseline)

    def _rough_line(self, image: Image.Image, x0: int, y0: int, x1: int, y1: int, width: int) -> None:
        draw = ImageDraw.Draw(image)
        points: list[tuple[int, int]] = []
        segments = max(2, round(abs(x1 - x0) / 18))
        for index in range(segments + 1):
            ratio = index / segments
            x = x0 + (x1 - x0) * ratio + self.random.gauss(0, 0.45)
            y = y0 + (y1 - y0) * ratio + self.random.gauss(0, 0.45)
            points.append((round(x), round(y)))
        draw.line(points, fill=self.engine.ink, width=width, joint="curve")


def _formula_lines(latex: str) -> list[str]:
    source = latex.strip()
    source = source.removeprefix("$$").removesuffix("$$").strip()
    source = source.removeprefix(r"\[").removesuffix(r"\]").strip()
    if re.search(r"\\begin\{(?:matrix|pmatrix|bmatrix|Bmatrix|vmatrix|Vmatrix|cases)\}", source):
        return [source]
    source = re.sub(r"\\begin\{(?:aligned|align|equation|gathered)\*?\}", "", source)
    source = re.sub(r"\\end\{(?:aligned|align|equation|gathered)\*?\}", "", source)
    return [line.strip() for line in re.split(r"\\\\", source) if line.strip()]


def _parse_grid_body(body: str) -> list[list[MathNode]]:
    rows: list[list[MathNode]] = []
    row: list[MathNode] = []
    buffer: list[str] = []
    depth = 0
    index = 0

    def flush_cell() -> None:
        source = "".join(buffer).strip()
        row.append(LatexMathParser(source).parse() if source else TextNode(""))
        buffer.clear()

    def flush_row() -> None:
        flush_cell()
        rows.append(row.copy())
        row.clear()

    while index < len(body):
        char = body[index]
        if char == "{" and (index == 0 or body[index - 1] != "\\"):
            depth += 1
        elif char == "}" and (index == 0 or body[index - 1] != "\\"):
            depth -= 1
        if depth == 0 and char == "&":
            flush_cell()
        elif depth == 0 and char == "\\" and index + 1 < len(body) and body[index + 1] == "\\":
            flush_row()
            index += 1
        else:
            buffer.append(char)
        index += 1
    if buffer or row:
        flush_row()
    return rows
