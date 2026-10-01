"""Regression tests for shared paragraph wrapping and visible line boundaries."""

import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from markdown_to_handwrite.config import ReportConfig
from markdown_to_handwrite.markdown_parser import InlinePart, ParagraphBlock, parse_markdown
from markdown_to_handwrite.math_renderer import MathBox
from markdown_to_handwrite.renderer import ReportRenderer


class LineLayoutTests(unittest.TestCase):
    def make_report(self, *, width=100, indent=0, justify=False, spacing=0):
        config = ReportConfig()
        config.page.dpi = 72
        config.background.style = "plain"
        config.background.paper_color = "#ffffff"
        config.background.auto_discover = False
        config.background.draw_margin_line = False
        config.handwriting.prefer_handright = False
        config.handwriting.sdt_trajectory_enabled = False
        config.handwriting.second_layer_enabled = False
        config.handwriting.perturb_theta_sigma = 0
        config.handwriting.perturb_x_sigma_px = 0
        config.handwriting.perturb_y_sigma_px = 0
        config.handwriting.line_spacing = 2
        config.handwriting.word_spacing_px = spacing
        config.layout.first_line_indent_em = indent
        config.layout.justify_paragraphs = justify
        config.layout.show_page_numbers = False
        report = ReportRenderer(config)
        report.content_w = width
        return report

    def fixed_text_engine(self, report, *, padding=0):
        """Known glyph advances; optional ink overhang exposes raster overflow."""
        def advance(char):
            return 5 if char.isspace() else max(1, 10 + report.config.handwriting.word_spacing_px)

        def measure(text, size_px, **kwargs):
            return sum(advance(char) for char in text)

        def render(text, size_px, max_width, **kwargs):
            # The real handwriting engine also trims terminal whitespace. The
            # layout therefore has to preserve spaces before a following formula.
            text = text.rstrip()
            width = max(1, round(measure(text, size_px)) + padding)
            image = Image.new("RGBA", (width, 12), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            x = 0
            for char in text:
                step = advance(char)
                if not char.isspace():
                    draw.rectangle((x, 2, x + max(1, step - 2), 9), fill=report.engine.ink)
                x += step
            if text and padding:
                draw.rectangle((max(0, x - 2), 2, width - 1, 9), fill=report.engine.ink)
            image.info["layout_test_text"] = text
            return (image, 9) if kwargs.get("return_baseline") else image

        return patch.multiple(report.engine, measure=measure, render_line=render)

    def render_and_capture(self, report, parts):
        pasted = []
        original = report._paste_rich_line

        def capture(line, x, y, max_width, *args, **kwargs):
            pasted.append((line, x, y, max_width))
            return original(line, x, y, max_width, *args, **kwargs)

        with patch.object(report, "_paste_rich_line", side_effect=capture):
            report.render([ParagraphBlock(parts)])
        return pasted

    @staticmethod
    def text_of(line):
        return "".join(image.info.get("layout_test_text", "") for image, _ in line.visuals)

    def assert_inside_lines(self, report, pasted):
        self.assertTrue(pasted)
        for line, x, _, available in pasted:
            self.assertLessEqual(line.width, available)
            self.assertLessEqual(x + line.width, report.margin_left + report.content_w)
        for page in report.pages:
            ink = ImageChops.difference(page.convert("RGB"), Image.new("RGB", page.size, "white"))
            bbox = ink.getbbox()
            if bbox:
                self.assertLessEqual(bbox[2], report.margin_left + report.content_w)

    def test_first_line_indent_does_not_shorten_subsequent_lines(self):
        report = self.make_report(indent=2)
        text = "甲" * 30
        with self.fixed_text_engine(report):
            pasted = self.render_and_capture(report, [InlinePart("text", text)])
        self.assertEqual([len(self.text_of(line)) for line, *_ in pasted], [6, 10, 10, 4])
        self.assertEqual([width for *_, width in pasted], [68, 100, 100, 100])
        self.assert_inside_lines(report, pasted)

    def test_long_ascii_token_wraps_without_losing_characters(self):
        report = self.make_report()
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
        with self.fixed_text_engine(report):
            pasted = self.render_and_capture(report, [InlinePart("text", text)])
        self.assertGreater(len(pasted), 1)
        self.assertEqual("".join(self.text_of(line) for line, *_ in pasted), text)
        self.assert_inside_lines(report, pasted)

    def test_long_closing_punctuation_sequence_cannot_overflow(self):
        report = self.make_report()
        text = "甲乙" + ")" * 35 + "尾"
        with self.fixed_text_engine(report):
            pasted = self.render_and_capture(report, [InlinePart("text", text)])
        self.assertGreater(len(pasted), 1)
        self.assertEqual("".join(self.text_of(line) for line, *_ in pasted), text)
        self.assert_inside_lines(report, pasted)

    def test_normal_closing_punctuation_stays_with_preceding_character(self):
        report = self.make_report()
        text = "甲" * 10 + ")乙"
        with self.fixed_text_engine(report):
            pasted = self.render_and_capture(report, [InlinePart("text", text)])
        self.assertGreater(len(pasted), 1)
        self.assertTrue(all(not self.text_of(line).startswith(")") for line, *_ in pasted))
        self.assertEqual("".join(self.text_of(line) for line, *_ in pasted), text)
        self.assert_inside_lines(report, pasted)

    def test_character_spacing_changes_the_number_of_wrapped_lines(self):
        counts = []
        for spacing in (0, 5):
            report = self.make_report(spacing=spacing)
            with self.fixed_text_engine(report):
                pasted = self.render_and_capture(report, [InlinePart("text", "甲" * 30)])
            self.assert_inside_lines(report, pasted)
            counts.append(len(pasted))
        self.assertGreater(counts[1], counts[0])

    def test_plain_and_br_paragraphs_wrap_the_same_leading_text(self):
        text = "甲乙丙丁戊己庚辛壬癸" * 3
        outputs = []
        for suffix in ([], [InlinePart("hardbreak"), InlinePart("text", "尾")]):
            report = self.make_report(indent=2)
            with self.fixed_text_engine(report):
                pasted = self.render_and_capture(report, [InlinePart("text", text), *suffix])
            outputs.append([self.text_of(line) for line, *_ in pasted])
        self.assertEqual(outputs[0], outputs[1][:-1])

    def test_raster_padding_is_accounted_for_before_pasting(self):
        report = self.make_report()
        text = "甲" * 26
        with self.fixed_text_engine(report, padding=9):
            pasted = self.render_and_capture(report, [InlinePart("text", text)])
        self.assertEqual("".join(self.text_of(line) for line, *_ in pasted), text)
        self.assert_inside_lines(report, pasted)

    def test_inline_formula_wider_than_indented_first_line_stays_inside(self):
        report = self.make_report(indent=2)
        formula_image = Image.new("RGBA", (90, 14), report.engine.ink)
        box = MathBox(formula_image, baseline=10)
        with self.fixed_text_engine(report), patch.object(report.formula_renderer, "render_inline", return_value=box):
            pasted = self.render_and_capture(report, [InlinePart("math", "x"), InlinePart("text", "尾")])
        self.assertEqual("".join(self.text_of(line) for line, *_ in pasted), "尾")
        self.assert_inside_lines(report, pasted)

    def test_explicit_spaces_on_both_sides_of_inline_math_are_preserved(self):
        widths = []
        for before, after in (("A", "B"), ("A ", " B")):
            report = self.make_report(width=200)
            formula_image = Image.new("RGBA", (20, 12), report.engine.ink)
            box = MathBox(formula_image, baseline=9)
            with self.fixed_text_engine(report), patch.object(report.formula_renderer, "render_inline", return_value=box):
                pasted = self.render_and_capture(
                    report,
                    [InlinePart("text", before), InlinePart("math", "x"), InlinePart("text", after)],
                )
            self.assertEqual(len(pasted), 1)
            widths.append(pasted[0][0].width)
        self.assertEqual(widths[1] - widths[0], 10)

    def test_enabling_justification_stretches_only_natural_nonfinal_lines(self):
        right_edges = []
        for justify in (False, True):
            report = self.make_report(width=105, justify=justify)
            with self.fixed_text_engine(report):
                pasted = self.render_and_capture(report, [InlinePart("text", "甲" * 16)])
            self.assertEqual(len(pasted), 2)
            right_edges.append(self.line_ink_width(report, pasted[0]))
            self.assertEqual(self.line_ink_width(report, pasted[1]), 59)
        self.assertGreater(right_edges[1], right_edges[0])

    def test_explicit_break_lines_are_not_stretched(self):
        for kind in ("break", "hardbreak"):
            widths = []
            for justify in (False, True):
                report = self.make_report(width=105, justify=justify)
                with self.fixed_text_engine(report):
                    pasted = self.render_and_capture(
                        report,
                        [InlinePart("text", "甲" * 10), InlinePart(kind), InlinePart("text", "乙")],
                    )
                self.assertEqual(len(pasted), 2)
                widths.append(self.line_ink_width(report, pasted[0]))
            with self.subTest(kind=kind):
                self.assertEqual(widths[0], widths[1])

    def test_naturally_wrapped_text_before_br_still_justifies(self):
        widths = []
        for justify in (False, True):
            report = self.make_report(width=105, justify=justify)
            with self.fixed_text_engine(report):
                pasted = self.render_and_capture(
                    report,
                    [InlinePart("text", "甲" * 16), InlinePart("hardbreak"), InlinePart("text", "乙")],
                )
            widths.append(self.line_ink_width(report, pasted[0]))
            self.assertEqual(self.line_ink_width(report, pasted[1]), 59)
        self.assertGreater(widths[1], widths[0])

    def test_short_natural_line_is_not_excessively_stretched(self):
        for first_word in ("AAAA", "AAAAAAAA"):
            widths = []
            for justify in (False, True):
                report = self.make_report(width=100, justify=justify)
                with self.fixed_text_engine(report):
                    pasted = self.render_and_capture(
                        report, [InlinePart("text", first_word + " BBBBBBBB")],
                    )
                self.assertGreater(len(pasted), 1)
                widths.append(self.line_ink_width(report, pasted[0]))
            with self.subTest(first_word=first_word):
                self.assertEqual(widths[0], widths[1])

    def test_large_indent_leaves_a_valid_first_line_budget(self):
        report = self.make_report(width=60, indent=12)
        with self.fixed_text_engine(report):
            pasted = self.render_and_capture(report, [InlinePart("text", "甲乙丙丁戊己庚辛")])
        self.assertTrue(all(width > 0 for *_, width in pasted))
        self.assert_inside_lines(report, pasted)

    @staticmethod
    def line_ink_width(report, pasted_line):
        line, _, y, _ = pasted_line
        stripe = report.pages[0].crop((0, y, report.page_w, y + line.height)).convert("RGB")
        bbox = ImageChops.difference(stripe, Image.new("RGB", stripe.size, "white")).getbbox()
        return 0 if bbox is None else bbox[2] - bbox[0]

    def test_real_handwriting_with_wide_spacing_and_jitter_stays_inside(self):
        report = self.make_report(width=145, indent=2, spacing=5)
        report.config.handwriting.second_layer_enabled = True
        report.config.handwriting.perturb_x_sigma_px = 2
        report.config.handwriting.perturb_theta_sigma = 0.02
        parts = parse_markdown("LongIdentifier0123456789甲乙，丙丁 $x+1$ 后文<br>第二行。")
        pasted = []
        original = report._paste_rich_line

        def capture(line, x, y, max_width, *args, **kwargs):
            pasted.append((line, x, y, max_width))
            return original(line, x, y, max_width, *args, **kwargs)

        with patch.object(report, "_paste_rich_line", side_effect=capture):
            report.render(parts)
        self.assertGreater(len(pasted), 2)
        self.assert_inside_lines(report, pasted)

    def test_cooling_rate_paragraph_preserves_formulas_and_right_margin(self):
        source = (
            "### 3. 冷却速率与散热面积修正\n\n"
            r"记录稳态温度后，移去橡胶盘，使铜盘与传热圆筒直接接触，加热至比 $T_2$ "
            r"高约 $10\,{}^\circ\mathrm C$，再移开传热圆筒，使铜盘自然冷却。"
            r"测量铜盘温度随时间的变化，求出其在 $T_2$ 附近的冷却速率。"
        )
        report = self.make_report(width=310, indent=2, spacing=2)
        original_paste = report._paste_rich_line
        original_formula = report.formula_renderer.render_inline
        pasted = []

        def capture(line, x, y, max_width, *args, **kwargs):
            pasted.append((line, x, y, max_width))
            return original_paste(line, x, y, max_width, *args, **kwargs)

        def mark_formula(latex, *args, **kwargs):
            box = original_formula(latex, *args, **kwargs)
            box.image.info["layout_test_formula"] = latex
            return box

        stderr = StringIO()
        with (
            redirect_stderr(stderr),
            patch.object(report, "_paste_rich_line", side_effect=capture),
            patch.object(report.formula_renderer, "render_inline", side_effect=mark_formula),
        ):
            report.render(parse_markdown(source))

        formulas = [
            image
            for line, *_ in pasted
            for image, _ in line.visuals
            if "layout_test_formula" in image.info
        ]
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            [image.info["layout_test_formula"] for image in formulas],
            ["T_2", r"10\,{}^\circ\mathrm C", "T_2"],
        )
        self.assertTrue(all(image.getchannel("A").getbbox() for image in formulas))
        self.assertTrue(any(x == report.margin_left + 32 for _, x, _, _ in pasted))
        self.assertGreater(len(pasted), 3)
        self.assert_inside_lines(report, pasted)


if __name__ == "__main__":
    unittest.main()
