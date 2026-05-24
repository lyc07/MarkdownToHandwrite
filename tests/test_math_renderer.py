import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from handwritten_report.config import ReportConfig, load_config
from handwritten_report.handwriting import HandwritingEngine
from handwritten_report.math_renderer import FormulaRenderer, LatexRenderError
from handwritten_report.markdown_parser import FormulaBlock, parse_markdown
from handwritten_report.renderer import ReportRenderer


class FormulaRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = HandwritingEngine(load_config("examples/config.json").handwriting)
        cls.renderer = FormulaRenderer(engine, seed=42)

    def test_fraction_creates_vertical_layout(self):
        plain = self.renderer.render("g = 4", 34, 900)
        fraction = self.renderer.render(r"g = \frac{4\pi^2 l}{T^2}", 34, 900)
        self.assertGreater(fraction.height, plain.height)
        self.assertIsNotNone(fraction.getchannel("A").getbbox())

    def test_root_and_accent_render(self):
        image = self.renderer.render(r"\bar{g} = 2\pi\sqrt{\frac{l}{g}}", 34, 900)
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 34)

    def test_inline_formula_exposes_math_baseline(self):
        box = self.renderer.render_inline(r"T=2\pi\sqrt{l/g}", 32, 600)
        self.assertGreater(box.baseline, 0)
        self.assertGreater(box.height, 32)

    def test_unsupported_command_raises_instead_of_becoming_text(self):
        with self.assertRaises(LatexRenderError):
            self.renderer.render(r"y = \unsupported{x}", 34, 900)

    def test_scripts_stay_near_the_base_line(self):
        base = self.renderer.render_inline("U", 42, 600)
        scripted = self.renderer.render_inline(r"U_{H}^{2}", 42, 600)
        self.assertLess(scripted.height, base.height + 42)

    def test_report_renderer_leaves_invalid_formula_blank_and_logs_source(self):
        config = ReportConfig()
        config.background.auto_discover = False
        report = ReportRenderer(config)
        output = StringIO()
        with redirect_stderr(output):
            image = report._render_formula_image(r"y=\unsupported{x}", "test")
        self.assertIsNone(image.getchannel("A").getbbox())
        self.assertIn(r"y=\unsupported{x}", output.getvalue())

    def test_common_calculus_and_set_commands_render(self):
        image = self.renderer.render(
            r"I=\iint_{D_1} f\,du\,dv,\quad D=\{x\mid x\ge0\}\setminus\emptyset,\quad 45^\circ,\quad x\to\infin",
            34,
            1900,
        )
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_indexed_root_accents_and_binomial_render(self):
        image = self.renderer.render(
            r"x=\sqrt[3]{a}+\hat{v}+\dot{x}+\binom{n}{k}",
            38,
            1400,
        )
        self.assertGreater(image.height, 38)

    def test_matrix_and_cases_render_as_two_dimensional_structures(self):
        matrix = self.renderer.render(r"A=\begin{bmatrix}a&b\\c&d\end{bmatrix}", 36, 1200)
        cases = self.renderer.render(r"f(x)=\begin{cases}x,&x\ge0\\-x,&x<0\end{cases}", 36, 1200)
        self.assertGreater(matrix.height, 36)
        self.assertGreater(cases.height, 36)

    def test_extended_example_math_is_supported(self):
        source = Path("examples/test.md").read_text(encoding="utf-8")
        blocks = parse_markdown(source)
        formulas: list[str] = []
        for block in blocks:
            if isinstance(block, FormulaBlock):
                formulas.append(block.text)
            formulas.extend(
                part.text
                for part in getattr(block, "parts", [])
                if getattr(part, "kind", None) == "math"
            )
        self.assertGreater(len(formulas), 20)
        for formula in formulas:
            with self.subTest(formula=formula):
                self.renderer.render_inline(formula, 32, 1600)


if __name__ == "__main__":
    unittest.main()
