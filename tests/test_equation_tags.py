import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from PIL import Image

from markdown_to_handwrite.config import HandwritingConfig, ReportConfig
from markdown_to_handwrite.handwriting import HandwritingEngine
from markdown_to_handwrite.markdown_parser import parse_markdown
from markdown_to_handwrite.math_renderer import FormulaRenderer, LatexRenderError, MathBox
from markdown_to_handwrite.renderer import ReportRenderer


BLUE = (15, 55, 220, 255)
GREEN = (15, 180, 40, 255)
RED = (220, 35, 15, 255)


class RectangleFormulaRenderer(FormulaRenderer):
    """Use measurable glyphs to test placement independently of handwriting jitter."""

    def __init__(self, engine):
        super().__init__(engine, seed=17)
        self.text_calls = []

    def _text_box(self, text, size_px, seed_extra):
        self.text_calls.append(text)
        if text and set(text) == {"x"}:
            fill = BLUE
        elif text and set(text) == {"y"}:
            fill = GREEN
        else:
            fill = RED
        return MathBox(Image.new("RGBA", (max(1, len(text) * 12), 24), fill), 18)


def color_bbox(image, color):
    mask = Image.new("L", image.size)
    mask.putdata([255 if pixel == color else 0 for pixel in image.getdata()])
    return mask.getbbox()


def occupied_row_runs(image, color):
    rows = []
    for y in range(image.height):
        if color in image.crop((0, y, image.width, y + 1)).getdata():
            rows.append(y)
    runs = []
    for y in rows:
        if not runs or y != runs[-1][1]:
            runs.append([y, y + 1])
        else:
            runs[-1][1] += 1
    return runs


class EquationTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = HandwritingEngine(
            HandwritingConfig(prefer_handright=False, sdt_trajectory_enabled=False)
        )

    def setUp(self):
        self.renderer = RectangleFormulaRenderer(self.engine)

    def test_tag_adds_parentheses_and_tag_star_preserves_label(self):
        for source, expected in (
            (r"x\tag{1}", "(1)"),
            (r"x\tag*{A.1}", "A.1"),
            (r"x\tag * {A.1}", "A.1"),
        ):
            with self.subTest(source=source):
                renderer = RectangleFormulaRenderer(self.engine)
                renderer.render(source, 24, 600)
                label = "".join(text for text in renderer.text_calls if text != "x")
                self.assertEqual(label, expected)

    def test_labels_support_nested_groups_text_and_math_commands(self):
        for source, label_parts in (
            (r"x\tag{\text{A.{1}}}", ["A.", "1"]),
            (r"x\tag{\alpha_1}", ["α", "1"]),
            (r"x\tag*{\{A\}}", ["{", "A", "}"]),
        ):
            with self.subTest(source=source):
                renderer = RectangleFormulaRenderer(self.engine)
                image = renderer.render(source, 24, 600)
                label = "".join(text for text in renderer.text_calls if text != "x")
                for part in label_parts:
                    self.assertIn(part, label)
                self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_tag_is_right_aligned_and_body_stays_centered(self):
        image = self.renderer.render(r"x\tag{1}", 24, 600)
        body = color_bbox(image, BLUE)
        label = color_bbox(image, RED)
        self.assertIsNotNone(body)
        self.assertIsNotNone(label)
        self.assertEqual(image.width, 600)
        self.assertAlmostEqual((body[0] + body[2]) / 2, image.width / 2, delta=1)
        self.assertEqual(label[2], image.width)
        self.assertGreater(label[0], body[2])
        self.assertEqual(body[1:4:2], label[1:4:2])

    def test_narrow_layout_moves_tag_below_without_clipping_body(self):
        image = self.renderer.render(r"xxxxxxxxxx\tag*{1234567890}", 24, 160)
        body = color_bbox(image, BLUE)
        label = color_bbox(image, RED)
        self.assertEqual(image.width, 160)
        self.assertIsNotNone(body)
        self.assertIsNotNone(label)
        self.assertEqual(body[2] - body[0], 120)
        self.assertEqual(label[2] - label[0], 120)
        self.assertEqual(body[3] - body[1], 24)
        self.assertEqual(label[3] - label[1], 24)
        self.assertGreaterEqual(label[1], body[3])
        self.assertEqual(label[2], image.width)

    def test_oversized_formula_and_tag_fit_available_width(self):
        image = self.renderer.render(r"xxxxxxxxxxxxxxxxxxxx\tag*{12345678901234567890}", 24, 80)
        body = color_bbox(image, BLUE)
        label = color_bbox(image, RED)
        self.assertEqual(image.width, 80)
        self.assertIsNotNone(body)
        self.assertIsNotNone(label)
        self.assertEqual(body[0], 0)
        self.assertEqual(body[2], 80)
        self.assertEqual(label[0], 0)
        self.assertEqual(label[2], 80)
        self.assertGreaterEqual(label[1], body[3])

    def test_align_tags_belong_to_their_respective_rows(self):
        image = self.renderer.render(r"\begin{align}x\tag{1}\\y\tag{2}\end{align}", 24, 600)
        first_body = color_bbox(image, BLUE)
        second_body = color_bbox(image, GREEN)
        labels = occupied_row_runs(image, RED)
        self.assertEqual(len(labels), 2)
        self.assertEqual(labels[0], [first_body[1], first_body[3]])
        self.assertEqual(labels[1], [second_body[1], second_body[3]])
        self.assertLess(first_body[3], second_body[1])

    def test_tag_after_aligned_group_is_centered_on_the_whole_group(self):
        image = self.renderer.render(r"\begin{aligned}x\\y\end{aligned}\tag{1}", 24, 600)
        first_body = color_bbox(image, BLUE)
        second_body = color_bbox(image, GREEN)
        label = color_bbox(image, RED)
        self.assertEqual(len(occupied_row_runs(image, RED)), 1)
        self.assertAlmostEqual(
            (label[1] + label[3]) / 2,
            (first_body[1] + second_body[3]) / 2,
            delta=2,
        )

    def test_multiline_equation_wrapper_can_have_one_group_tag(self):
        image = self.renderer.render(
            r"\begin{equation}\begin{aligned}x\\y\end{aligned}\tag{1}\end{equation}",
            24,
            600,
        )
        self.assertIsNotNone(color_bbox(image, BLUE))
        self.assertIsNotNone(color_bbox(image, GREEN))
        self.assertEqual(len(occupied_row_runs(image, RED)), 1)

    def test_styles_and_delimiters_around_multiline_groups_still_render_with_tags(self):
        for source in (
            r"\displaystyle\begin{aligned}x\\y\end{aligned}\tag{1}",
            r"\left\{\begin{aligned}x\\y\end{aligned}\right.\tag{1}",
        ):
            with self.subTest(source=source):
                renderer = RectangleFormulaRenderer(self.engine)
                image = renderer.render(source, 24, 600)
                first_body = color_bbox(image, BLUE)
                second_body = color_bbox(image, GREEN)
                self.assertIsNotNone(first_body)
                self.assertIsNotNone(second_body)
                self.assertLess(first_body[3], second_body[1])
                self.assertEqual(renderer.text_calls.count("1"), 1)

    def test_real_handwriting_supports_matrix_cases_and_nested_multiline_tags(self):
        sources = (
            r"\begin{pmatrix}a&b\\c&d\end{pmatrix}\tag{1}",
            r"f(x)=\begin{cases}x&x>0\\0&x\leq0\end{cases}\tag*{A}",
            r"\begin{aligned}x&=\begin{pmatrix}a\\b\end{pmatrix}\\y&=2\end{aligned}\tag{3}",
        )
        for source in sources:
            with self.subTest(source=source):
                renderer = FormulaRenderer(self.engine, seed=11)
                image = renderer.render(source, 32, 900)
                self.assertIsNotNone(image.getchannel("A").getbbox())
                self.assertLessEqual(image.width, 900)

    def test_inline_tags_are_rejected_even_with_multiple_lines(self):
        for source in (r"x\tag{1}", r"x\tag*{A}", r"x\\y\tag{2}", r"\begin{aligned}x\\y\end{aligned}\tag{1}"):
            with self.subTest(source=source):
                with self.assertRaises(LatexRenderError):
                    self.renderer.render_inline(source, 24, 600)

    def test_malformed_tags_duplicate_tags_and_different_commands_are_rejected(self):
        for source in (
            r"x\tag",
            r"x\tag1",
            r"x\tag*",
            r"x\tag{1",
            r"x\tag{1}\tag{2}",
            r"x\tag*{1}\tag{2}",
            r"x\tagged{1}",
            r"\begin{aligned}x\tag{1}\\y\end{aligned}\tag{2}",
        ):
            with self.subTest(source=source):
                with self.assertRaises(LatexRenderError):
                    self.renderer.render(source, 24, 600)

    def test_untagged_formula_remains_tightly_cropped(self):
        image = self.renderer.render("x", 24, 600)
        self.assertEqual(image.size, (12, 24))

    def test_markdown_report_renders_valid_tags_without_formula_errors(self):
        config = ReportConfig()
        config.page.dpi = 72
        config.background.auto_discover = False
        config.handwriting.prefer_handright = False
        config.handwriting.sdt_trajectory_enabled = False
        report = ReportRenderer(config)
        stderr = StringIO()
        with patch.object(report.formula_renderer, "render", wraps=report.formula_renderer.render) as render:
            with redirect_stderr(stderr):
                pages = report.render(parse_markdown("$$\nx=1\\tag{1}\n$$\n\n$$\ny=2\\tag*{A}\n$$"))
        self.assertTrue(pages)
        self.assertEqual(render.call_count, 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn(r"\tag{1}", render.call_args_list[0].args[0])
        self.assertIn(r"\tag*{A}", render.call_args_list[1].args[0])


if __name__ == "__main__":
    unittest.main()
