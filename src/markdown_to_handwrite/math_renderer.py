from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .handwriting import HandwritingEngine, _vary_ink_density
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
    "lbrace": "{",
    "rbrace": "}",
    "backslash": "\\",
    "ldots": "...",
    "cdots": "...",
    "dots": "...",
    "varpi": "ϖ",
    "varrho": "ϱ",
    "varsigma": "ς",
    "oplus": "⊕",
    "ominus": "⊖",
    "otimes": "⊗",
    "oslash": "⊘",
    "odot": "⊙",
    "bullet": "•",
    "star": "⋆",
    "diamond": "◇",
    "cong": "≅",
    "simeq": "≃",
    "asymp": "≍",
    "doteq": "≐",
    "prec": "≺",
    "succ": "≻",
    "preceq": "≼",
    "succeq": "≽",
    "ni": "∋",
    "owns": "∋",
    "vdash": "⊢",
    "dashv": "⊣",
    "models": "⊨",
    "iff": "⇔",
    "implies": "⇒",
    "impliedby": "⇐",
    "longrightarrow": "⟶",
    "longleftarrow": "⟵",
    "longleftrightarrow": "⟷",
    "Longrightarrow": "⟹",
    "Longleftarrow": "⟸",
    "Longleftrightarrow": "⟺",
    "uparrow": "↑",
    "downarrow": "↓",
    "updownarrow": "↕",
    "Uparrow": "⇑",
    "Downarrow": "⇓",
    "Updownarrow": "⇕",
    "therefore": "∴",
    "because": "∵",
    "Re": "ℜ",
    "Im": "ℑ",
    "aleph": "ℵ",
    "hbar": "ℏ",
    "ell": "ℓ",
}
COMMAND_TEXT = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "ln", "log", "lg", "exp", "lim", "max", "min",
    "sup", "inf", "det", "dim", "ker", "arg", "gcd", "Pr", "limsup", "liminf",
}
FONT_WRAPPER_COMMANDS = {
    "mathrm", "mathbf", "mathit", "mathbb", "mathcal", "mathscr", "mathsf", "mathtt",
    "boldsymbol", "bm", "text", "textrm", "textsf", "texttt", "textnormal", "textbf",
    "textit", "emph", "mbox", "substack", "smash",
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
INTEGRAL_SYMBOLS = {"∫", "∬", "∭", "∮"}
LIMIT_OPERATOR_SYMBOLS = INTEGRAL_SYMBOLS | {"∑", "∏"}
LIMIT_OPERATOR_NAMES = {"lim", "max", "min", "sup", "inf"}


class LatexRenderError(ValueError):
    pass


@dataclass(frozen=True)
class TextNode:
    text: str


@dataclass(frozen=True)
class OperatorNameNode:
    text: str


@dataclass(frozen=True)
class SpaceNode:
    factor: float


@dataclass(frozen=True)
class IgnoreNode:
    limit_mode: str | None = None


@dataclass(frozen=True)
class StyleNode:
    display_style: bool


@dataclass(frozen=True)
class GeneratedSymbolNode:
    kind: str
    count: int = 1


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
class LimitsNode:
    base: "MathNode"
    mode: str


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


MathNode = TextNode | OperatorNameNode | SpaceNode | IgnoreNode | StyleNode | GeneratedSymbolNode | RowNode | FractionNode | RootNode | ScriptNode | LimitsNode | AccentNode | BinomialNode | MatrixNode


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
                if isinstance(command_node, IgnoreNode):
                    if command_node.limit_mode and items:
                        items[-1] = LimitsNode(items[-1], command_node.limit_mode)
                else:
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
            elif char == "'":
                flush_text()
                count = 0
                while self.index < len(self.source) and self.source[self.index] == "'":
                    count += 1
                    self.index += 1
                prime = GeneratedSymbolNode("prime", count)
                base = items.pop() if items else TextNode("")
                if isinstance(base, TextNode) and len(base.text) > 1:
                    items.append(TextNode(base.text[:-1]))
                    base = TextNode(base.text[-1])
                if isinstance(base, ScriptNode):
                    superscript = (
                        prime
                        if base.superscript is None
                        else RowNode([base.superscript, SpaceNode(0.04), prime])
                    )
                    base = ScriptNode(base.base, superscript, base.subscript)
                elif isinstance(base, TextNode) and not base.text:
                    base = prime
                else:
                    base = ScriptNode(base, superscript=prime)
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
        if command in {"overrightarrow", "overleftarrow", "overleftrightarrow"}:
            return AccentNode(self._parse_argument(), "vec")
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
        if command in {"limits", "nolimits", "displaylimits"}:
            return IgnoreNode(command)
        if command in {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle"}:
            return StyleNode(command == "displaystyle")
        if command in {"left", "right"}:
            return SpaceNode(0)
        if command in {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr"}:
            return SpaceNode(0)
        if command in {"quad", "qquad"}:
            return SpaceNode(1.0 if command == "quad" else 2.0)
        if command in {"mod", "bmod"}:
            return OperatorNameNode("mod")
        if command == "pmod":
            return RowNode([
                TextNode("("),
                OperatorNameNode("mod"),
                SpaceNode(0.16),
                self._parse_argument(),
                TextNode(")"),
            ])
        if command == "cdot":
            return GeneratedSymbolNode("cdot")
        if command == "prime":
            return GeneratedSymbolNode("prime")
        if command in COMMAND_SYMBOLS:
            return TextNode(COMMAND_SYMBOLS[command])
        if command in COMMAND_TEXT:
            return OperatorNameNode(command)
        if command == "operatorname":
            if self.index < len(self.source) and self.source[self.index] == "*":
                self.index += 1
            return self._parse_argument()
        if command in FONT_WRAPPER_COMMANDS:
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
        self._ink_random = random.Random(f"{seed}|ink")
        self._weight_seed_extra: str | None = None

    def render(self, latex: str, size_px: int, max_width: int, seed_extra: str = "") -> Image.Image:
        latex = westernize_punctuation(latex)
        line_boxes: list[MathBox] = []
        for index, line in enumerate(_formula_lines(latex)):
            if not line.strip():
                continue
            line_seed = f"{seed_extra}:display:{index}"
            line_boxes.append(
                self._layout_with_weight_group(
                    LatexMathParser(line).parse(),
                    size_px,
                    line_seed,
                    display_style=True,
                )
            )
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
        box = self._layout_with_weight_group(
            LatexMathParser(lines[0]).parse(),
            size_px,
            f"{seed_extra}:inline",
            display_style=False,
        )
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

    def _layout_with_weight_group(
        self,
        node: MathNode,
        size_px: int,
        seed_extra: str,
        display_style: bool,
    ) -> MathBox:
        previous = self._weight_seed_extra
        self._weight_seed_extra = seed_extra
        try:
            return self._layout(node, size_px, seed_extra, display_style)
        finally:
            self._weight_seed_extra = previous

    def draw_horizontal_rule(
        self,
        image: Image.Image,
        x0: float,
        y: float,
        x1: float,
        size_px: int,
        width: float = 1,
        fill: tuple[int, ...] | None = None,
        anchor_ends: bool = False,
        variation_scale: float = 1.0,
    ) -> None:
        self.draw_rule(
            image,
            x0,
            y,
            x1,
            y,
            size_px,
            width=width,
            fill=fill,
            anchor_ends=anchor_ends,
            variation_scale=variation_scale,
        )

    def draw_rule(
        self,
        image: Image.Image,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        size_px: int,
        width: float = 1,
        fill: tuple[int, ...] | None = None,
        anchor_ends: bool = False,
        variation_scale: float = 1.0,
    ) -> None:
        if self.engine.uses_sdt_trajectories:
            width = self._stroke_width(size_px)
        tilt, bend, jitter = self._rule_variation(size_px)
        scale = max(0.0, variation_scale)
        tilt *= scale
        bend *= scale
        jitter *= scale
        distance = math.hypot(x1 - x0, y1 - y0)
        if distance <= 0:
            return
        if not anchor_ends:
            normal_x = -(y1 - y0) / distance
            normal_y = (x1 - x0) / distance
            x1 += normal_x * tilt
            y1 += normal_y * tilt
        self._pen_stroke(
            image,
            self._rule_curve(x0, y0, x1, y1, bend, jitter, size_px),
            width,
            fill=fill,
        )

    def _layout(self, node: MathNode, size_px: int, seed_extra: str, display_style: bool = False) -> MathBox:
        if isinstance(node, TextNode):
            return self._text_box(node.text, size_px, seed_extra)
        if isinstance(node, OperatorNameNode):
            return self._text_box(node.text, size_px, seed_extra)
        if isinstance(node, SpaceNode):
            width = max(0, round(size_px * node.factor))
            return MathBox(Image.new("RGBA", (max(1, width), size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        if isinstance(node, (IgnoreNode, StyleNode)):
            return MathBox(Image.new("RGBA", (1, size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        if isinstance(node, GeneratedSymbolNode):
            return self._generated_symbol_box(node, size_px, seed_extra)
        if isinstance(node, LimitsNode):
            return self._layout(node.base, size_px, seed_extra, display_style)
        if isinstance(node, RowNode):
            boxes: list[MathBox] = []
            current_style = display_style
            for index, child in enumerate(node.items):
                if isinstance(child, StyleNode):
                    current_style = child.display_style
                    continue
                boxes.append(self._layout(child, size_px, f"{seed_extra}:row:{index}", current_style))
            return self._row_box(boxes, size_px)
        if isinstance(node, FractionNode):
            return self._fraction_box(node, size_px, seed_extra)
        if isinstance(node, RootNode):
            return self._root_box(node, size_px, seed_extra, display_style)
        if isinstance(node, ScriptNode):
            return self._script_box(node, size_px, seed_extra, display_style)
        if isinstance(node, BinomialNode):
            return self._binomial_box(node, size_px, seed_extra)
        if isinstance(node, MatrixNode):
            return self._matrix_box(node, size_px, seed_extra)
        return self._accent_box(node, size_px, seed_extra, display_style)

    def _text_box(self, text: str, size_px: int, seed_extra: str) -> MathBox:
        if not text:
            return MathBox(Image.new("RGBA", (1, size_px), (0, 0, 0, 0)), round(size_px * 0.75))
        width = max(16, round(self.engine.measure(text, size_px, math=True) + 2 * size_px))
        image, baseline = self.engine.render_line(
            text,
            size_px,
            width,
            seed_extra=seed_extra,
            math=True,
            weight_seed_extra=self._weight_seed_extra,
            return_baseline=True,
        )
        return MathBox(image, max(1, baseline))

    def _generated_symbol_box(
        self,
        node: GeneratedSymbolNode,
        size_px: int,
        seed_extra: str,
    ) -> MathBox:
        """Draw small math marks whose glyph-font outlines are unsuitable."""
        stroke = self._stroke_width(size_px)
        x_sigma = self.engine._glyph_position_sigma(
            size_px,
            self.engine.config.perturb_x_sigma_px,
        )
        y_sigma = self.engine._vertical_position_sigma(size_px, math_mode=True)
        symbol_random = random.Random(f"{seed_extra}|{node.kind}|{node.count}")
        dx = self.engine._sample_position_offset(symbol_random, x_sigma)
        dy = self.engine._sample_position_offset(symbol_random, y_sigma)
        x_room = math.ceil(3.0 * x_sigma + stroke + 1)
        y_room = math.ceil(3.0 * y_sigma + stroke + 1)

        if node.kind == "cdot":
            body_width = max(7, round(size_px * 0.28))
            body_height = max(8, size_px)
            baseline = y_room + round(size_px * 0.75)
            image = Image.new(
                "RGBA",
                (body_width + 2 * x_room, body_height + 2 * y_room),
                (0, 0, 0, 0),
            )
            center_x = x_room + body_width / 2.0 + dx
            center_y = y_room + size_px * 0.49 + dy
            dot_width = max(stroke * 1.45, size_px * 0.075)
            self._pen_stroke(
                image,
                [(center_x - 0.25, center_y), (center_x + 0.25, center_y)],
                dot_width,
            )
            return MathBox(image, baseline)

        if node.kind == "prime":
            count = max(1, node.count)
            mark_width = max(4, round(size_px * 0.18))
            gap = max(1, round(size_px * 0.04))
            body_width = count * mark_width + (count - 1) * gap
            body_height = max(8, round(size_px * 0.62))
            baseline = y_room + round(size_px * 0.58)
            image = Image.new(
                "RGBA",
                (body_width + 2 * x_room, body_height + 2 * y_room),
                (0, 0, 0, 0),
            )
            top = y_room + size_px * 0.07 + dy
            bottom = y_room + size_px * 0.43 + dy
            slant = max(1.0, size_px * 0.07)
            for index in range(count):
                right = x_room + (index + 1) * mark_width + index * gap - stroke + dx
                self._pen_stroke(
                    image,
                    [(right, top), (right - slant, bottom)],
                    stroke,
                )
            return MathBox(image, baseline)

        raise LatexRenderError(f"Unsupported generated symbol: {node.kind}")

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
        rule_overhang = max(3, round(size_px * 0.12))
        side_pad = rule_overhang + max(2, round(size_px * 0.05))
        gap = max(3, round(size_px * 0.12))
        stroke = self._stroke_width(size_px)
        stroke_extent = max(1, math.ceil(stroke))
        tilt, bend, jitter = self._rule_variation(size_px)
        rule_slack = max(2, round(abs(tilt) + abs(bend) + jitter + stroke_extent))
        width = max(numerator.width, denominator.width) + 2 * side_pad
        bar_y = numerator.height + gap + rule_slack
        denominator_y = bar_y + stroke_extent + gap + rule_slack
        height = denominator_y + denominator.height
        baseline = min(height - 1, bar_y + stroke_extent + round(size_px * 0.28))
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        image.alpha_composite(numerator.image, ((width - numerator.width) // 2, 0))
        image.alpha_composite(denominator.image, ((width - denominator.width) // 2, denominator_y))
        rule_x0 = side_pad - rule_overhang
        rule_x1 = width - side_pad + rule_overhang
        self._pen_stroke(
            image,
            self._rule_curve(rule_x0, bar_y, rule_x1, bar_y + tilt, bend, jitter, size_px),
            stroke,
        )
        return MathBox(image, baseline)

    def _root_box(self, node: RootNode, size_px: int, seed_extra: str, display_style: bool = False) -> MathBox:
        body = self._layout(node.body, size_px, f"{seed_extra}:body", display_style)
        index = self._layout(node.index, max(8, round(size_px * 0.48)), f"{seed_extra}:index") if node.index else None
        contains_fraction = _contains_fraction(node.body)
        stroke = self._stroke_width(size_px)
        stroke_extent = max(1, math.ceil(stroke))
        tilt, bend, jitter = self._rule_variation(size_px)
        rule_slack = max(2, round(abs(tilt) + abs(bend) + jitter + stroke_extent))
        rule_y = rule_slack + max(stroke_extent + 1, round(size_px * 0.07))
        lowest_rule_y = rule_y + max(0, tilt) + abs(bend) + jitter
        body_gap = max(2, round(size_px * (0.025 if contains_fraction else 0.045)))
        body_y = round(lowest_rule_y) + stroke_extent + body_gap
        baseline = body_y + body.baseline
        radical_height = max(1, baseline - rule_y)
        radical_ratio = 0.34 if contains_fraction else 0.4
        radical_width = max(round(size_px * 0.46), round(radical_height * radical_ratio))
        prefix_w = max(0, (index.width - round(radical_width * 0.32)) if index else 0)
        body_x = prefix_w + radical_width
        end_pad = max(2, round(size_px * (0.06 if contains_fraction else 0.08)))
        width = body_x + body.width + end_pad
        valley_depth = round(size_px * (0.32 if contains_fraction else 0.08))
        valley_y = min(body_y + body.height - 1, baseline + valley_depth)
        height = max(body_y + body.height, valley_y + stroke_extent + 1, index.height if index else 0)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if index:
            image.alpha_composite(index.image, (0, 0))
        image.alpha_composite(body.image, (body_x, body_y))
        rule_curve = self._rule_curve(body_x, rule_y, width - 1, rule_y + tilt, bend, jitter, size_px)
        self._pen_stroke(
            image,
            [
                (prefix_w + 1, baseline - round(size_px * 0.03)),
                (prefix_w + round(radical_width * 0.2), valley_y),
                (prefix_w + round(radical_width * 0.34), valley_y - round(size_px * 0.03)),
                *rule_curve,
            ],
            stroke,
        )
        return MathBox(image, baseline)

    def _script_box(self, node: ScriptNode, size_px: int, seed_extra: str, display_style: bool = False) -> MathBox:
        symbol, limit_mode = self._operator_limit_mode(node.base)
        if symbol and self._should_stack_limits(symbol, limit_mode, display_style):
            return self._operator_limits_box(node, size_px, seed_extra)
        if symbol in INTEGRAL_SYMBOLS:
            return self._integral_side_scripts_box(node, size_px, seed_extra, display_style)
        base = self._layout(node.base, size_px, f"{seed_extra}:base", display_style)
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

    def _integral_side_scripts_box(
        self,
        node: ScriptNode,
        size_px: int,
        seed_extra: str,
        display_style: bool = False,
    ) -> MathBox:
        base = self._layout(node.base, size_px, f"{seed_extra}:base", display_style)
        script_size = max(9, round(size_px * 0.54))
        superscript = self._layout(node.superscript, script_size, f"{seed_extra}:sup") if node.superscript else None
        subscript = self._layout(node.subscript, script_size, f"{seed_extra}:sub") if node.subscript else None
        raise_by = round(size_px * 0.57)
        lower_by = round(size_px * 0.25)
        initial_sup_y = base.baseline - raise_by - superscript.baseline if superscript else 0
        base_y = max(0, -initial_sup_y)
        baseline = base_y + base.baseline
        sup_x = max(1, base.width - round(size_px * 0.09))
        sub_x = max(1, base.width - round(size_px * 0.24))
        sup_y = base_y + initial_sup_y
        sub_y = baseline + lower_by - subscript.baseline if subscript else 0
        width = max(
            base.width,
            sup_x + superscript.width if superscript else 0,
            sub_x + subscript.width if subscript else 0,
        )
        height = base_y + base.height
        if superscript:
            height = max(height, sup_y + superscript.height)
        if subscript:
            height = max(height, sub_y + subscript.height)
        image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
        image.alpha_composite(base.image, (0, base_y))
        if superscript:
            image.alpha_composite(superscript.image, (sup_x, sup_y))
        if subscript:
            image.alpha_composite(subscript.image, (sub_x, sub_y))
        return MathBox(image, baseline)

    def _operator_limit_mode(self, node: MathNode) -> tuple[str | None, str | None]:
        mode = None
        if isinstance(node, LimitsNode):
            mode = node.mode
            node = node.base
        if isinstance(node, TextNode) and node.text in LIMIT_OPERATOR_SYMBOLS:
            return node.text, mode
        if isinstance(node, OperatorNameNode) and node.text in LIMIT_OPERATOR_NAMES:
            return node.text, mode
        return None, mode

    def _should_stack_limits(self, symbol: str, limit_mode: str | None, display_style: bool) -> bool:
        if limit_mode == "limits":
            return True
        if limit_mode == "nolimits":
            return False
        if limit_mode == "displaylimits":
            return display_style
        return display_style and symbol not in INTEGRAL_SYMBOLS

    def _operator_limits_box(self, node: ScriptNode, size_px: int, seed_extra: str) -> MathBox:
        base = self._layout(node.base, size_px, f"{seed_extra}:base")
        script_size = max(9, round(size_px * 0.5))
        superscript = self._layout(node.superscript, script_size, f"{seed_extra}:sup") if node.superscript else None
        subscript = self._layout(node.subscript, script_size, f"{seed_extra}:sub") if node.subscript else None
        gap = max(1, round(size_px * 0.025))
        symbol, _ = self._operator_limit_mode(node.base)
        is_integral = symbol in INTEGRAL_SYMBOLS
        script_shift = round(size_px * 0.05) if is_integral else 0
        width = max(
            base.width,
            (superscript.width + abs(script_shift)) if superscript else 0,
            (subscript.width + abs(script_shift)) if subscript else 0,
        )
        base_y = superscript.height + gap if superscript else 0
        sub_y = base_y + base.height + gap
        height = base_y + base.height + (gap + subscript.height if subscript else 0)
        image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
        image.alpha_composite(base.image, ((width - base.width) // 2, base_y))
        if superscript:
            image.alpha_composite(superscript.image, ((width - superscript.width) // 2 + script_shift, 0))
        if subscript:
            image.alpha_composite(subscript.image, ((width - subscript.width) // 2 - script_shift, sub_y))
        return MathBox(image, base_y + base.baseline)

    def _accent_box(self, node: AccentNode, size_px: int, seed_extra: str, display_style: bool = False) -> MathBox:
        body = self._layout(node.body, size_px, f"{seed_extra}:body", display_style)
        if node.kind in {"bar", "overline", "underline", "vec"}:
            stroke = self._stroke_width(size_px)
            stroke_extent = max(1, math.ceil(stroke))
            tilt, bend, jitter = self._rule_variation(size_px)
            rule_slack = max(2, round(abs(tilt) + abs(bend) + jitter + stroke_extent))
            accent_h = max(4, round(size_px * 0.2), 2 * rule_slack + stroke_extent + 1)
            rule_y = rule_slack
            if node.kind == "underline":
                image = Image.new("RGBA", (body.width + 2, body.height + accent_h), (0, 0, 0, 0))
                image.alpha_composite(body.image, (1, 0))
                rule_y += body.height
                baseline = body.baseline
            else:
                image = Image.new("RGBA", (body.width + 2, body.height + accent_h), (0, 0, 0, 0))
                image.alpha_composite(body.image, (1, accent_h))
                baseline = body.baseline + accent_h
            self._pen_stroke(
                image,
                self._rule_curve(2, rule_y, body.width, rule_y + tilt, bend, jitter, size_px),
                stroke,
            )
            if node.kind == "vec":
                end_y = rule_y + tilt
                self._pen_stroke(
                    image,
                    [
                        (body.width - round(size_px * 0.16), end_y - round(size_px * 0.11)),
                        (body.width, end_y),
                    ],
                    stroke if self.engine.uses_sdt_trajectories else max(1, round(size_px / 22)),
                )
            return MathBox(image, baseline)
        accent_h = max(4, round(size_px * 0.2))
        stroke = (
            self._stroke_width(size_px)
            if self.engine.uses_sdt_trajectories
            else max(1, round(size_px / 20))
        )
        image = Image.new("RGBA", (body.width + 2, body.height + accent_h), (0, 0, 0, 0))
        image.alpha_composite(body.image, (1, accent_h))
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
            self._pen_stroke(
                image,
                [(2, accent_h - 2), (body.width // 3, 1), (2 * body.width // 3, accent_h - 2), (body.width, 1)],
                stroke,
            )
        else:
            self._rough_line(image, 2, accent_h - 2, body.width, accent_h - 2, stroke)
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

    def _rough_line(self, image: Image.Image, x0: int, y0: int, x1: int, y1: int, width: float) -> None:
        points: list[tuple[int, int]] = []
        segments = max(2, round(abs(x1 - x0) / 18))
        for index in range(segments + 1):
            ratio = index / segments
            x = x0 + (x1 - x0) * ratio + self.random.gauss(0, 0.45)
            y = y0 + (y1 - y0) * ratio + self.random.gauss(0, 0.45)
            points.append((round(x), round(y)))
        if self.engine.uses_sdt_trajectories:
            self._pen_stroke(image, points, width)
            return
        draw = ImageDraw.Draw(image)
        draw.line(points, fill=self.engine.ink, width=max(1, round(width)), joint="curve")

    def _pen_stroke(
        self,
        image: Image.Image,
        anchors: list[tuple[float, float]],
        width: float,
        fill: tuple[int, ...] | None = None,
    ) -> None:
        if len(anchors) < 2:
            return
        scale = 6
        weight_group = self._weight_seed_extra or "generated-rules"
        edge_adjustment = self.engine.grouped_stroke_weight_adjustment(weight_group, math_mode=True)
        minimum_width = 0.35 if self.engine.uses_sdt_trajectories else 1.15
        base_width_px = max(minimum_width, float(width) + 2 * edge_adjustment)
        padding = max(3, math.ceil(base_width_px * 1.6 + 2))
        x0 = max(0, math.floor(min(x for x, _ in anchors) - padding))
        y0 = max(0, math.floor(min(y for _, y in anchors) - padding))
        x1 = min(image.width, math.ceil(max(x for x, _ in anchors) + padding + 1))
        y1 = min(image.height, math.ceil(max(y for _, y in anchors) + padding + 1))
        if x1 <= x0 or y1 <= y0:
            return
        local_size = (x1 - x0, y1 - y0)
        layer = Image.new("RGBA", (local_size[0] * scale, local_size[1] * scale), (0, 0, 0, 0))
        points = [((x - x0) * scale, (y - y0) * scale) for x, y in anchors]
        draw = ImageDraw.Draw(layer)
        base_width = base_width_px * scale
        pressure_jitter = (
            min(0.8, max(0.0, self.engine.config.sdt_width_jitter))
            if self.engine.uses_sdt_trajectories
            else 0.0
        )
        taper = (
            min(0.8, max(0.0, self.engine.config.sdt_taper))
            if self.engine.uses_sdt_trajectories
            else 0.22
        )
        pressure_phase = self._ink_random.uniform(0.0, math.tau)
        pressure_cycles = self._ink_random.uniform(0.6, 1.4)
        radii: list[float] = []
        normals: list[tuple[float, float]] = []
        last_index = len(points) - 1
        for index, (x, y) in enumerate(points):
            previous = points[max(0, index - 1)]
            following = points[min(last_index, index + 1)]
            dx = following[0] - previous[0]
            dy = following[1] - previous[1]
            distance = max(0.001, math.hypot(dx, dy))
            normals.append((-dy / distance, dx / distance))
            ratio = index / last_index
            pressure = 1.0 - taper * (1.0 - math.sin(math.pi * ratio) ** 0.55)
            pressure += 0.025 * math.sin(3 * math.pi * ratio)
            pressure *= 1.0 + pressure_jitter * 0.45 * math.sin(
                math.tau * pressure_cycles * ratio + pressure_phase
            )
            radii.append(max(scale * 0.36, base_width * pressure / 2))
        polygon_left = [
            (x + normal_x * radius, y + normal_y * radius)
            for (x, y), (normal_x, normal_y), radius in zip(points, normals, radii)
        ]
        polygon_right = [
            (x - normal_x * radius, y - normal_y * radius)
            for (x, y), (normal_x, normal_y), radius in zip(points, normals, radii)
        ]
        stroke_fill = fill or self.engine.ink
        draw.polygon([*polygon_left, *reversed(polygon_right)], fill=stroke_fill)
        for (x, y), radius in zip(points, radii):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=stroke_fill)
        layer = layer.resize(local_size, Image.Resampling.LANCZOS)
        if self.engine.config.second_layer_enabled:
            alpha = _vary_ink_density(
                layer.getchannel("A"),
                self._ink_random,
                jitter=self.engine.config.ink_density_jitter,
                dry_brush_probability=self.engine.config.dry_brush_probability,
                dry_brush_min_opacity=self.engine.config.dry_brush_min_opacity,
            )
            layer.putalpha(alpha)
        image.alpha_composite(layer, (x0, y0))

    def _rule_variation(self, size_px: int) -> tuple[float, float, float]:
        tilt_range = max(0.0, size_px * self.engine.config.math_rule_tilt_ratio)
        bend_range = max(0.0, size_px * self.engine.config.math_rule_wobble_ratio)
        jitter_range = max(0.0, size_px * self.engine.config.math_rule_jitter_ratio)
        return (
            self.random.uniform(-tilt_range, tilt_range),
            self.random.uniform(-bend_range, bend_range),
            jitter_range,
        )

    def _stroke_width(self, size_px: int) -> float:
        if self.engine.uses_sdt_trajectories:
            return self.engine.uniform_pen_width_px()
        return max(1, round(size_px * 0.024))

    def _rule_curve(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        bend: float,
        jitter: float,
        size_px: int,
    ) -> list[tuple[float, float]]:
        delta_x = x1 - x0
        delta_y = y1 - y0
        distance = max(1.0, math.hypot(delta_x, delta_y))
        normal_x = -delta_y / distance
        normal_y = delta_x / distance
        jitter_count = self._rule_jitter_count(distance, size_px) if jitter > 0 else 0
        offsets = [0.0]
        offsets.extend(self._rule_jitter_offset(jitter) for _ in range(jitter_count))
        offsets.append(0.0)
        steps = max(8, (jitter_count + 1) * 8)
        points: list[tuple[float, float]] = []
        for step in range(steps + 1):
            ratio = step / steps
            offset_position = ratio * (len(offsets) - 1)
            offset_index = min(len(offsets) - 2, math.floor(offset_position))
            offset_ratio = offset_position - offset_index
            offset_ratio = offset_ratio**3 * (offset_ratio * (offset_ratio * 6 - 15) + 10)
            local_jitter = offsets[offset_index] + (offsets[offset_index + 1] - offsets[offset_index]) * offset_ratio
            endpoint_fade = math.sin(math.pi * ratio) ** 0.65
            normal_offset = bend * math.sin(math.pi * ratio) + local_jitter * endpoint_fade
            points.append(
                (
                    x0 + delta_x * ratio + normal_x * normal_offset,
                    y0 + delta_y * ratio + normal_y * normal_offset,
                )
            )
        return points

    def _rule_jitter_count(self, distance: float, size_px: int) -> int:
        writing_units = distance / max(1.0, size_px * 2.0)
        return max(1, min(6, math.ceil(math.log2(1 + writing_units))))

    def _rule_jitter_offset(self, jitter: float) -> float:
        magnitude = self.random.uniform(jitter * 0.35, jitter)
        return magnitude if self.random.random() < 0.5 else -magnitude


def _contains_fraction(node: MathNode) -> bool:
    if isinstance(node, FractionNode):
        return True
    if isinstance(node, RowNode):
        return any(_contains_fraction(child) for child in node.items)
    if isinstance(node, ScriptNode):
        return any(
            _contains_fraction(child)
            for child in (node.base, node.superscript, node.subscript)
            if child is not None
        )
    if isinstance(node, LimitsNode):
        return _contains_fraction(node.base)
    if isinstance(node, RootNode):
        return _contains_fraction(node.body) or (node.index is not None and _contains_fraction(node.index))
    if isinstance(node, AccentNode):
        return _contains_fraction(node.body)
    if isinstance(node, BinomialNode):
        return _contains_fraction(node.upper) or _contains_fraction(node.lower)
    if isinstance(node, MatrixNode):
        return any(_contains_fraction(cell) for row in node.rows for cell in row)
    return False


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
