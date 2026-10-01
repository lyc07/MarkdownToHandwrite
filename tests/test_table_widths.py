import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from PIL import Image, ImageChops

from markdown_to_handwrite.config import ReportConfig, mm_to_px, pt_to_px
from markdown_to_handwrite.markdown_parser import InlinePart, TableBlock, parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer


def cell(text):
    return [InlinePart("text", text)]


class TableWidthTests(unittest.TestCase):
    def make_report(self, *, width=340, padding_mm=2):
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
        config.handwriting.advance_jitter_sigma_ratio = 0
        config.handwriting.word_spacing_px = 0
        config.layout.table_cell_padding_mm = padding_mm
        config.layout.show_page_numbers = False
        report = ReportRenderer(config)
        report.content_w = width
        return report

    @staticmethod
    def table_size(report):
        return pt_to_px(report.config.handwriting.body_font_pt - 1, report.dpi)

    def widths(self, report, table):
        count = max([len(table.headers), *[len(row) for row in table.rows]])
        return report._table_widths(table, count, self.table_size(report))

    def assert_valid_budget(self, widths, available):
        self.assertTrue(all(isinstance(width, int) and width > 0 for width in widths), widths)
        self.assertEqual(sum(widths), available)

    def test_many_columns_keep_positive_widths_and_exact_total(self):
        for count, available in ((10, 50), (12, 127), (25, 501)):
            with self.subTest(count=count, available=available):
                report = self.make_report(width=available)
                table = TableBlock([cell("A") for _ in range(count)], [[cell("1") for _ in range(count)]])
                widths = self.widths(report, table)
                self.assertEqual(len(widths), count)
                self.assert_valid_budget(widths, available)

    def test_equal_content_gets_equal_widths_up_to_one_rounding_pixel(self):
        for count, available in ((3, 107), (7, 301), (10, 503)):
            with self.subTest(count=count, available=available):
                report = self.make_report(width=available)
                table = TableBlock([cell("Header") for _ in range(count)], [[cell("12.5") for _ in range(count)]])
                widths = self.widths(report, table)
                self.assert_valid_budget(widths, available)
                self.assertLessEqual(max(widths) - min(widths), 1)

    def test_column_and_row_permutations_do_not_penalize_the_last_column(self):
        report = self.make_report(width=323)
        table = TableBlock(
            [cell("ID"), cell("Value"), cell("Description")],
            [[cell("1"), cell("20.5"), cell("A detailed description " * 8)],
             [cell("2"), cell("17.4"), cell("Short description")]],
        )
        original = self.widths(report, table)
        self.assert_valid_budget(original, report.content_w)
        for order in ((2, 0, 1), (1, 2, 0), (2, 1, 0)):
            with self.subTest(order=order):
                permuted = TableBlock(
                    [table.headers[index] for index in order],
                    [[row[index] for index in order] for row in reversed(table.rows)],
                )
                widths = self.widths(report, permuted)
                self.assert_valid_budget(widths, report.content_w)
                for index, width in zip(order, widths):
                    self.assertLessEqual(abs(width - original[index]), 1)

    def test_extreme_description_leaves_room_for_short_labels_and_numbers(self):
        report = self.make_report(width=340)
        table = TableBlock(
            [cell("说明"), cell("编号"), cell("温度")],
            [[cell("很长的实验说明文字" * 80), cell("12"), cell("20.0")]],
        )
        widths = self.widths(report, table)
        size = self.table_size(report)
        pad = mm_to_px(report.config.layout.table_cell_padding_mm, report.dpi)
        self.assert_valid_budget(widths, report.content_w)
        self.assertGreater(widths[0], widths[1])
        self.assertGreater(widths[0], widths[2])
        self.assertGreaterEqual(widths[1] - 2 * pad, report.engine.measure("编号", size))
        self.assertGreaterEqual(widths[2] - 2 * pad, report.engine.measure("20.0", size))

    def test_fraction_column_uses_two_dimensional_width_instead_of_flattened_source(self):
        report = self.make_report(width=340)
        latex = r"\frac{123456}{123456}"
        text = "1234567890"
        size = self.table_size(report)
        formula = report.formula_renderer.render_inline(latex, size, 2000, seed_extra="table-width-reference")
        self.assertLess(formula.width, report.engine.measure(text, size))
        table = TableBlock([cell("A"), cell("B")], [[[InlinePart("math", latex)], cell(text)]])
        widths = self.widths(report, table)
        self.assert_valid_budget(widths, report.content_w)
        self.assertLess(widths[0], widths[1])

    def test_short_handwritten_header_includes_ink_padding_before_wrapping(self):
        config = ReportConfig()
        config.page.dpi = 150
        config.background.style = "plain"
        config.background.auto_discover = False
        report = ReportRenderer(config)
        table = TableBlock(
            [cell("序号"), cell("测量值"), cell("说明")],
            [[cell("1"), cell("25.6"), cell("记录温度随时间的变化。" * 40)]],
        )
        widths = self.widths(report, table)
        size = self.table_size(report)
        pad = mm_to_px(config.layout.table_cell_padding_mm, report.dpi)
        cells, _ = report._table_row_layout(
            table.headers, widths, size, round(size * config.handwriting.line_spacing), pad, "table:header",
        )
        self.assertEqual(len(cells[1]), 1)
        self.assertLessEqual(cells[1][0].width, widths[1] - 2 * pad)

    def test_explicit_breaks_measure_the_longest_line_not_the_combined_text(self):
        report = self.make_report(width=307)
        one_line = TableBlock([cell("A"), cell("B")], [[cell("abcdefghij"), cell("short")]])
        with_break = TableBlock(
            one_line.headers,
            [[[InlinePart("text", "abcdefghij"), InlinePart("hardbreak"), InlinePart("text", "abcdefghij")], cell("short")]],
        )
        self.assertEqual(self.widths(report, one_line), self.widths(report, with_break))

    def test_padding_is_part_of_column_demand(self):
        table = TableBlock([cell("ID"), cell("Description")], [[cell("1"), cell("A longer description of the experiment")]])
        unpadded = self.make_report(width=300, padding_mm=0)
        padded = self.make_report(width=300, padding_mm=8)
        without_pad = self.widths(unpadded, table)
        with_pad = self.widths(padded, table)
        self.assert_valid_budget(without_pad, 300)
        self.assert_valid_budget(with_pad, 300)
        self.assertGreater(with_pad[0], without_pad[0])
        pad = mm_to_px(8, padded.dpi)
        self.assertGreater(with_pad[0], 2 * pad)

    def test_narrow_cells_use_the_same_positive_layout_and_paste_budget(self):
        report = self.make_report(width=50, padding_mm=2)
        table = TableBlock([cell("A") for _ in range(10)], [[cell("1") for _ in range(10)]])
        line_budgets = {}
        pasted = []
        original_layout = report._layout_rich_parts
        original_paste = report._paste_rich_line

        def layout(parts, size, max_width, *args, **kwargs):
            lines = original_layout(parts, size, max_width, *args, **kwargs)
            for line in lines:
                line_budgets[id(line)] = max_width
            return lines

        def paste(line, x, y, max_width, *args, **kwargs):
            pasted.append((line, x, max_width))
            self.assertGreater(max_width, 0)
            self.assertEqual(max_width, line_budgets[id(line)])
            self.assertLessEqual(line.width, max_width)
            return original_paste(line, x, y, max_width, *args, **kwargs)

        with patch.object(report, "_layout_rich_parts", side_effect=layout), patch.object(report, "_paste_rich_line", side_effect=paste):
            report.render([table])
        self.assertEqual(len(pasted), 20)
        for _, x, max_width in pasted:
            self.assertGreaterEqual(x, report.margin_left)
            self.assertLessEqual(x + max_width, report.margin_left + report.content_w)
            self.assertLessEqual(max_width, 5)

    def test_measuring_widths_preserves_formula_random_state_and_later_output(self):
        report = self.make_report()
        control = self.make_report()
        table = TableBlock([cell("A"), cell("B")], [[[InlinePart("math", r"\sqrt{\frac{a}{b}}")], cell("value")]])
        geometry_state = report.formula_renderer.random.getstate()
        ink_state = report.formula_renderer._ink_random.getstate()
        first = self.widths(report, table)
        second = self.widths(report, table)
        self.assertEqual(first, second)
        self.assertEqual(report.formula_renderer.random.getstate(), geometry_state)
        self.assertEqual(report.formula_renderer._ink_random.getstate(), ink_state)
        expected = control.formula_renderer.render_inline(r"\sqrt{x}+\frac{a}{b}", 24, 1000, seed_extra="after-measure")
        actual = report.formula_renderer.render_inline(r"\sqrt{x}+\frac{a}{b}", 24, 1000, seed_extra="after-measure")
        self.assertEqual((actual.baseline, actual.image.size, actual.image.tobytes()), (expected.baseline, expected.image.size, expected.image.tobytes()))

    def test_real_table_with_math_and_breaks_renders_inside_positive_cell_budgets(self):
        report = self.make_report(width=310)
        blocks = parse_markdown(
            "| 编号 | 测量值 | 说明 |\n| --- | --- | --- |\n"
            r"| 1 | $\frac{12}{5}$ | 第一行<br>第二行 |" + "\n"
            r"| 2 | $\sqrt{x+1}$ | 较长的说明内容用于检查换行和列宽分配。 |"
        )
        budgets = []
        original = report._paste_rich_line

        def paste(line, x, y, max_width, *args, **kwargs):
            budgets.append(max_width)
            self.assertGreater(max_width, 0)
            self.assertLessEqual(line.width, max_width)
            return original(line, x, y, max_width, *args, **kwargs)

        stderr = StringIO()
        with redirect_stderr(stderr), patch.object(report, "_paste_rich_line", side_effect=paste):
            report.render(blocks)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(budgets)
        self.assertTrue(any(
            ImageChops.difference(page.convert("RGB"), Image.new("RGB", page.size, "white")).getbbox()
            for page in report.pages
        ))


if __name__ == "__main__":
    unittest.main()
