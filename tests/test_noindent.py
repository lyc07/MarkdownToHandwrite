import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

from markdown_to_handwrite.config import ReportConfig, pt_to_px
from markdown_to_handwrite.markdown_parser import (
    CodeBlock,
    FormulaBlock,
    HeadingBlock,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    TableBlock,
    parse_markdown,
    parts_to_text,
)
from markdown_to_handwrite.renderer import ReportRenderer


def paragraphs(blocks):
    return [block for block in blocks if isinstance(block, ParagraphBlock)]


class NoIndentParserTests(unittest.TestCase):
    def test_ordinary_paragraphs_keep_default_indentation(self):
        blocks = paragraphs(parse_markdown("First\n\nSecond"))
        self.assertEqual([block.no_indent for block in blocks], [False, False])

    def test_tag_variants_mark_one_paragraph_and_are_not_visible(self):
        for tag in ("<noindent>", "<noindent/>", "<NOINDENT />", '<NoIndent class="body" data-note="a > b">'):
            with self.subTest(tag=tag):
                blocks = paragraphs(parse_markdown(tag + "First\n\nSecond"))
                self.assertEqual([parts_to_text(block.parts) for block in blocks], ["First", "Second"])
                self.assertEqual([block.no_indent for block in blocks], [True, False])

    def test_marker_in_the_middle_or_end_affects_the_current_paragraph(self):
        for source in ("A<noindent>B", "AB<noindent>"):
            with self.subTest(source=source):
                blocks = paragraphs(parse_markdown(source + "\n\nNext"))
                self.assertEqual([parts_to_text(block.parts) for block in blocks], ["AB", "Next"])
                self.assertEqual([block.no_indent for block in blocks], [True, False])

    def test_repeated_markers_are_idempotent(self):
        blocks = paragraphs(parse_markdown("<noindent><NOINDENT/>A<noindent>\n\nB"))
        self.assertEqual([parts_to_text(block.parts) for block in blocks], ["A", "B"])
        self.assertEqual([block.no_indent for block in blocks], [True, False])

    def test_marker_on_either_side_of_opening_p_targets_that_paragraph(self):
        for source in ("<p><noindent>A</p><p>B</p>", "<noindent><p>A</p><p>B</p>"):
            with self.subTest(source=source):
                blocks = paragraphs(parse_markdown(source))
                self.assertEqual([parts_to_text(block.parts) for block in blocks], ["A", "B"])
                self.assertEqual([block.no_indent for block in blocks], [True, False])

    def test_standalone_marker_applies_once_with_or_without_a_blank_line(self):
        for separator in ("\n", "\n\n", "\n\n\n"):
            with self.subTest(separator=repr(separator)):
                blocks = paragraphs(parse_markdown("<noindent>" + separator + "A\n\nB"))
                self.assertEqual([parts_to_text(block.parts) for block in blocks], ["A", "B"])
                self.assertEqual([block.no_indent for block in blocks], [True, False])
                self.assertFalse(any(part.kind in {"break", "hardbreak"} for part in blocks[0].parts))

    def test_marker_only_does_not_create_an_empty_paragraph(self):
        for source in ("<noindent>", "<noindent/>\n", "<noindent>\n\n<NOINDENT/>"):
            with self.subTest(source=source):
                self.assertEqual(parse_markdown(source), [])

    def test_br_preserves_the_current_noindent_paragraph(self):
        blocks = paragraphs(parse_markdown("<noindent>A<br><br>B\n\nC"))
        self.assertEqual([parts_to_text(block.parts) for block in blocks], ["A\n\nB", "C"])
        self.assertEqual([block.no_indent for block in blocks], [True, False])
        self.assertEqual(sum(part.kind == "hardbreak" for part in blocks[0].parts), 2)

    def test_newpage_ends_marker_scope_and_a_new_marker_can_reapply_it(self):
        blocks = parse_markdown("<noindent>A<newpage>B<newpage><noindent>C")
        self.assertEqual(sum(isinstance(block, PageBreakBlock) for block in blocks), 2)
        body = paragraphs(blocks)
        self.assertEqual([parts_to_text(block.parts) for block in body], ["A", "B", "C"])
        self.assertEqual([block.no_indent for block in body], [True, False, True])

    def test_inline_fenced_and_indented_code_keep_the_literal_tag(self):
        blocks = parse_markdown("`<noindent>`\n\n```html\n<noindent>\n```\n\n    <noindent>\n\nAfter")
        body = paragraphs(blocks)
        self.assertEqual([parts_to_text(block.parts) for block in body], ["<noindent>", "After"])
        self.assertTrue(all(not block.no_indent for block in body))
        self.assertEqual([block.text for block in blocks if isinstance(block, CodeBlock)], ["<noindent>", "<noindent>"])

    def test_inline_and_display_math_keep_the_literal_tag(self):
        latex = r"\text{<noindent>}"
        blocks = parse_markdown(f"A ${latex}$ B\n\n$$\n{latex}\n$$\n\nAfter")
        body = paragraphs(blocks)
        self.assertTrue(all(not block.no_indent for block in body))
        self.assertEqual([part.text for part in body[0].parts if part.kind == "math"], [latex])
        self.assertEqual([block.text for block in blocks if isinstance(block, FormulaBlock)], [latex])

    def test_backslash_escaped_and_entity_tags_remain_literal(self):
        for source in (r"\<noindent>A", "&lt;noindent&gt;A"):
            with self.subTest(source=source):
                blocks = paragraphs(parse_markdown(source))
                self.assertEqual(parts_to_text(blocks[0].parts), "<noindent>A")
                self.assertFalse(blocks[0].no_indent)

    def test_headings_lists_and_tables_keep_the_literal_tag(self):
        blocks = parse_markdown("# <noindent>Heading\n\n- <noindent>Item\n\n| Header |\n| --- |\n| <noindent>Cell |\n\nAfter")
        heading = next(block for block in blocks if isinstance(block, HeadingBlock))
        sequence = next(block for block in blocks if isinstance(block, ListBlock))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        self.assertEqual(parts_to_text(heading.parts), "<noindent>Heading")
        self.assertEqual(parts_to_text(sequence.items[0]), "<noindent>Item")
        self.assertEqual(parts_to_text(table.rows[0][0]), "<noindent>Cell")
        self.assertFalse(paragraphs(blocks)[0].no_indent)

    def test_standalone_marker_does_not_leak_across_other_blocks(self):
        intervening = (
            "# Heading", "- Item", "```\ncode\n```", "$$\nx=1\n$$", "---",
            "<newpage>", "![Figure](image.png)", "| H |\n| --- |\n| C |",
        )
        for content in intervening:
            for separator in ("\n", "\n\n"):
                with self.subTest(content=content, separator=repr(separator)):
                    blocks = parse_markdown("<noindent>" + separator + content + "\n\nAfter")
                    body = paragraphs(blocks)
                    self.assertEqual([parts_to_text(block.parts) for block in body], ["After"])
                    self.assertFalse(body[0].no_indent)

    def test_root_directive_after_other_blocks_targets_the_following_paragraph(self):
        for prefix in ("- Item", "1. Item", "# Heading", "<newpage>"):
            with self.subTest(prefix=prefix):
                blocks = parse_markdown(prefix + "\n<noindent>\nA\n\nB")
                body = paragraphs(blocks)
                self.assertEqual([parts_to_text(block.parts) for block in body], ["A", "B"])
                self.assertEqual([block.no_indent for block in body], [True, False])
                if isinstance(blocks[0], ListBlock):
                    self.assertEqual(parts_to_text(blocks[0].items[0]), "Item")

    def test_indented_directive_inside_a_list_stays_literal(self):
        blocks = parse_markdown("- Item\n  <noindent>\n  Continued\n\nAfter")
        self.assertIsInstance(blocks[0], ListBlock)
        self.assertEqual(parts_to_text(blocks[0].items[0]), "Item\n<noindent>\nContinued")
        self.assertEqual([parts_to_text(block.parts) for block in paragraphs(blocks)], ["After"])
        self.assertFalse(paragraphs(blocks)[0].no_indent)

    def test_inline_directive_does_not_swallow_adjacent_source_newlines(self):
        for source in ("A<noindent>\nB", "A\n<noindent>B"):
            with self.subTest(source=source):
                body = paragraphs(parse_markdown(source))
                self.assertEqual(len(body), 1)
                self.assertTrue(body[0].no_indent)
                self.assertEqual(parts_to_text(body[0].parts), "A\nB")

    def test_comments_and_attribute_values_do_not_activate_noindent(self):
        for source in ('A <!-- <noindent> --> B', '<span title="<noindent>">A</span>'):
            with self.subTest(source=source):
                blocks = paragraphs(parse_markdown(source))
                self.assertTrue(blocks)
                self.assertTrue(all(not block.no_indent for block in blocks))


class NoIndentRendererTests(unittest.TestCase):
    def make_report(self):
        config = ReportConfig()
        config.page.dpi = 72
        config.background.style = "plain"
        config.background.auto_discover = False
        config.background.draw_margin_line = False
        config.handwriting.prefer_handright = False
        config.handwriting.sdt_trajectory_enabled = False
        config.handwriting.second_layer_enabled = False
        config.handwriting.perturb_theta_sigma = 0
        config.handwriting.perturb_x_sigma_px = 0
        config.handwriting.perturb_y_sigma_px = 0
        config.handwriting.line_spacing = 2
        config.layout.first_line_indent_em = 2
        config.layout.justify_paragraphs = False
        config.layout.show_page_numbers = False
        report = ReportRenderer(config)
        report.content_w = 180
        return report

    def render_and_capture(self, source):
        report = self.make_report()
        pasted = []
        original = report._paste_rich_line

        def capture(line, x, y, max_width, *args, **kwargs):
            pasted.append((line, x, y, max_width, len(report.pages)))
            return original(line, x, y, max_width, *args, **kwargs)

        with patch.object(report, "_paste_rich_line", side_effect=capture):
            report.render(parse_markdown(source))
        self.assertEqual(report.config.layout.first_line_indent_em, 2)
        return report, pasted

    def test_noindent_changes_first_line_x_and_available_width(self):
        report, pasted = self.render_and_capture("<noindent>A\n\nB")
        self.assertEqual(len(pasted), 2)
        self.assertEqual([x for _, x, *_ in pasted], [report.margin_left, report.margin_left + 32])
        self.assertEqual([available for _, _, _, available, _ in pasted], [180, 148])

    def test_long_paragraph_uses_full_width_on_its_first_and_following_lines(self):
        source = "<noindent>" + "首行不应缩进而且长段落应完整折行。" * 5
        report, pasted = self.render_and_capture(source)
        self.assertGreater(len(pasted), 2)
        self.assertTrue(all(x == report.margin_left for _, x, *_ in pasted))
        self.assertTrue(all(available == 180 and line.width <= available for line, _, _, available, _ in pasted))

    def test_formula_paragraph_obeys_noindent_without_rendering_errors(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            report, pasted = self.render_and_capture(r"<noindent>由 $T_2$ 得到温度为 $10\,{}^\circ\mathrm C$，继续说明公式。")
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(pasted)
        self.assertEqual(pasted[0][1], report.margin_left)
        self.assertEqual(pasted[0][3], report.content_w)
        self.assertTrue(all(line.width <= available for line, _, _, available, _ in pasted))

    def test_consecutive_br_keep_blank_lines_and_next_paragraph_recovers_indent(self):
        report, pasted = self.render_and_capture("<noindent>A<br><br>B\n\nC")
        self.assertEqual(len(pasted), 4)
        self.assertEqual([x for _, x, *_ in pasted], [report.margin_left] * 3 + [report.margin_left + 32])
        line_h = round(pt_to_px(report.config.handwriting.body_font_pt, report.dpi) * report.config.handwriting.line_spacing)
        self.assertEqual(pasted[2][2] - pasted[0][2], line_h * 2)
        self.assertEqual(pasted[1][0].width, 0)

    def test_page_break_recovers_indent_and_new_marker_can_disable_it_again(self):
        report, pasted = self.render_and_capture("<noindent>A<newpage>B<newpage><noindent>C")
        self.assertEqual(len(report.pages), 3)
        self.assertEqual([page for *_, page in pasted], [1, 2, 3])
        self.assertEqual([x for _, x, *_ in pasted], [report.margin_left, report.margin_left + 32, report.margin_left])
        self.assertEqual([available for _, _, _, available, _ in pasted], [180, 148, 180])
        self.assertTrue(all(y == report.margin_top for _, _, y, _, _ in pasted))


if __name__ == "__main__":
    unittest.main()
