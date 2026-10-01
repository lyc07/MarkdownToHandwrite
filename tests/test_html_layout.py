import unittest
from contextlib import redirect_stderr
from io import StringIO

from PIL import Image, ImageChops

from markdown_to_handwrite.config import ReportConfig, pt_to_px
from markdown_to_handwrite.markdown_parser import (
    CodeBlock,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
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


def hardbreak_count(parts):
    return sum(part.kind == "hardbreak" for part in parts)


class HtmlLayoutParserTests(unittest.TestCase):
    def test_br_variants_create_explicit_inline_breaks(self):
        for tag in ("<br>", "<br/>", "<BR />", '<br class="line">'):
            with self.subTest(tag=tag):
                blocks = parse_markdown(f"A{tag}B")
                self.assertEqual(len(blocks), 1)
                self.assertIsInstance(blocks[0], ParagraphBlock)
                self.assertEqual(hardbreak_count(blocks[0].parts), 1)
                self.assertEqual(parts_to_text(blocks[0].parts), "A\nB")

    def test_consecutive_and_leading_br_are_preserved(self):
        for source, expected in (("A<br><br>B", 2), ("<br>A", 1), ("<br><br>", 2)):
            with self.subTest(source=source):
                blocks = parse_markdown(source)
                self.assertEqual(len(blocks), 1)
                self.assertIsInstance(blocks[0], ParagraphBlock)
                self.assertEqual(hardbreak_count(blocks[0].parts), expected)
        self.assertEqual(parse_markdown("<br>A")[0].parts[0].kind, "hardbreak")

    def test_source_newlines_adjacent_to_br_do_not_double_the_break(self):
        for source in ("A<br>\nB", "A\n<br>B", "A\n<br>\nB"):
            with self.subTest(source=source):
                block = parse_markdown(source)[0]
                self.assertEqual(hardbreak_count(block.parts), 1)
                self.assertFalse(any(part.kind == "break" for part in block.parts))
                self.assertEqual(parts_to_text(block.parts), "A\nB")

    def test_p_tags_create_paragraph_boundaries(self):
        for source in (
            "<p>A</p><p>B</p>",
            '<P class="first">A</P>\n<p>B</p>',
            "A<p/>B",
            "A<p>B</p>",
        ):
            with self.subTest(source=source):
                blocks = parse_markdown(source)
                self.assertTrue(all(isinstance(block, ParagraphBlock) for block in blocks))
                self.assertEqual([parts_to_text(block.parts) for block in blocks], ["A", "B"])

    def test_p_tags_preserve_content_on_both_sides(self):
        blocks = parse_markdown("Before<p>Inside</p>After")
        self.assertEqual([parts_to_text(block.parts) for block in blocks], ["Before", "Inside", "After"])

    def test_controls_do_not_swallow_following_markdown_blocks(self):
        for prefix in ("<p>A</p>\n<p>B</p>", "<br>", "<newpage>"):
            with self.subTest(prefix=prefix):
                blocks = parse_markdown(prefix + "\n# Heading\n\n- Item\n")
                heading = next(block for block in blocks if isinstance(block, HeadingBlock))
                sequence = next(block for block in blocks if isinstance(block, ListBlock))
                self.assertEqual(parts_to_text(heading.parts), "Heading")
                self.assertEqual(parts_to_text(sequence.items[0]), "Item")

    def test_newpage_splits_inline_text_into_independent_blocks(self):
        for tag in ("<newpage>", "<newpage/>", "<NEWPAGE />"):
            with self.subTest(tag=tag):
                blocks = parse_markdown(f"A{tag}B")
                self.assertEqual([type(block) for block in blocks], [ParagraphBlock, PageBreakBlock, ParagraphBlock])
                self.assertEqual(parts_to_text(blocks[0].parts), "A")
                self.assertEqual(parts_to_text(blocks[2].parts), "B")

    def test_br_works_in_headings_lists_and_tables(self):
        blocks = parse_markdown("# A<br>B\n\n- A<br>B\n\n| Header |\n| --- |\n| A<br>B |")
        heading = next(block for block in blocks if isinstance(block, HeadingBlock))
        sequence = next(block for block in blocks if isinstance(block, ListBlock))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        for parts in (heading.parts, sequence.items[0], table.rows[0][0]):
            self.assertEqual(hardbreak_count(parts), 1)
            self.assertEqual(parts_to_text(parts), "A\nB")

    def test_standalone_newpage_ends_a_list_without_a_blank_line(self):
        for tag in ("<newpage>", '<NEWPAGE title="next > page"/>'):
            with self.subTest(tag=tag):
                blocks = parse_markdown(f"- Item\n{tag}\nNext")
                self.assertEqual([type(block) for block in blocks], [ListBlock, PageBreakBlock, ParagraphBlock])
                self.assertEqual(parts_to_text(blocks[0].items[0]), "Item")
                self.assertEqual(parts_to_text(blocks[2].parts), "Next")
        blocks = parse_markdown("- Item\n  <newpage>\n  Continued")
        self.assertEqual([type(block) for block in blocks], [ListBlock])
        self.assertIn("<newpage>", parts_to_text(blocks[0].items[0]))

    def test_paragraph_and_page_controls_remain_literal_outside_body_paragraphs(self):
        content = "A<p>B</p><newpage>C<br>D"
        blocks = parse_markdown(f"# {content}\n\n- {content}\n\n| Header |\n| --- |\n| {content} |")
        self.assertFalse(any(isinstance(block, PageBreakBlock) for block in blocks))
        heading = next(block for block in blocks if isinstance(block, HeadingBlock))
        sequence = next(block for block in blocks if isinstance(block, ListBlock))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        for parts in (heading.parts, sequence.items[0], table.rows[0][0]):
            text = parts_to_text(parts)
            self.assertIn("<p>", text)
            self.assertIn("</p>", text)
            self.assertIn("<newpage>", text)
            self.assertEqual(hardbreak_count(parts), 1)

    def test_inline_code_and_fenced_or_indented_code_preserve_tag_source(self):
        literal = "<br><p>A</p><newpage>"
        blocks = parse_markdown(f"`{literal}`\n\n```html\n{literal}\n```\n\n    {literal}\n")
        inline = paragraphs(blocks)[0]
        self.assertEqual([(part.kind, part.text) for part in inline.parts], [("code", literal)])
        code_blocks = [block for block in blocks if isinstance(block, CodeBlock)]
        self.assertEqual([block.text for block in code_blocks], [literal, literal])
        self.assertFalse(any(isinstance(block, PageBreakBlock) for block in blocks))

    def test_backslash_escaped_and_entity_tags_remain_literal(self):
        for source in (r"\<br> \<p> \</p> \<newpage>", "&lt;br&gt; &lt;p&gt; &lt;/p&gt; &lt;newpage&gt;"):
            with self.subTest(source=source):
                blocks = parse_markdown(source)
                self.assertEqual(len(blocks), 1)
                self.assertIsInstance(blocks[0], ParagraphBlock)
                self.assertEqual(hardbreak_count(blocks[0].parts), 0)
                self.assertEqual(parts_to_text(blocks[0].parts), "<br> <p> </p> <newpage>")

    def test_html_comments_and_attribute_values_are_not_layout_commands(self):
        blocks = parse_markdown('<!-- <br><p><newpage> -->\n\n<span title="<newpage>">A</span>')
        self.assertFalse(any(isinstance(block, PageBreakBlock) for block in blocks))
        self.assertTrue(all(hardbreak_count(block.parts) == 0 for block in paragraphs(blocks)))
        attribute_break = parse_markdown('A<br title="<newpage>">B')
        self.assertEqual(len(attribute_break), 1)
        self.assertEqual(hardbreak_count(attribute_break[0].parts), 1)

    def test_inline_math_and_display_math_preserve_tag_source(self):
        formula = r"\text{<br><p><newpage>}"
        blocks = parse_markdown(f"A ${formula}$ B \\({formula}\\)\n\n$$\n{formula}\\tag{{1}}\n$$")
        inline = paragraphs(blocks)[0]
        self.assertEqual([part.text for part in inline.parts if part.kind == "math"], [formula, formula])
        self.assertEqual(hardbreak_count(inline.parts), 0)
        display = next(block for block in blocks if isinstance(block, FormulaBlock))
        self.assertEqual(display.text, formula + r"\tag{1}")
        self.assertFalse(any(isinstance(block, PageBreakBlock) for block in blocks))

    def test_image_followed_by_page_control_does_not_swallow_the_heading(self):
        blocks = parse_markdown('<img src="x.png" alt="Figure">\n<newpage>\n# Next')
        self.assertEqual([type(block) for block in blocks], [ImageBlock, PageBreakBlock, HeadingBlock])
        self.assertEqual(blocks[0].src, "x.png")
        self.assertEqual(parts_to_text(blocks[2].parts), "Next")

    def test_paragraph_controls_preserve_text_around_inline_images(self):
        blocks = parse_markdown('<p>Before<img src="x.png" alt="<newpage>">After</p>')
        self.assertEqual([type(block) for block in blocks], [ParagraphBlock, ImageBlock, ParagraphBlock])
        self.assertEqual(parts_to_text(blocks[0].parts), "Before")
        self.assertEqual(blocks[1].alt, "<newpage>")
        self.assertEqual(parts_to_text(blocks[2].parts), "After")


class HtmlLayoutRendererTests(unittest.TestCase):
    def make_report(self):
        config = ReportConfig()
        config.page.dpi = 72
        config.background.auto_discover = False
        config.background.style = "plain"
        config.background.paper_color = "#ffffff"
        config.background.draw_margin_line = False
        config.handwriting.prefer_handright = False
        config.handwriting.sdt_trajectory_enabled = False
        config.handwriting.second_layer_enabled = False
        config.handwriting.perturb_theta_sigma = 0
        config.handwriting.perturb_x_sigma_px = 0
        config.handwriting.perturb_y_sigma_px = 0
        config.handwriting.math_perturb_y_sigma_ratio = 0
        config.handwriting.line_spacing = 2
        config.layout.show_page_numbers = False
        return ReportRenderer(config)

    def render_source(self, source):
        report = self.make_report()
        report.render(parse_markdown(source))
        return report

    @staticmethod
    def ink_bbox(page):
        return ImageChops.difference(page.convert("RGB"), Image.new("RGB", page.size, "white")).getbbox()

    def test_repeated_and_leading_br_consume_full_blank_lines(self):
        normal = self.render_source("A<br>B")
        repeated = self.render_source("A<br><br>B")
        leading = self.render_source("<br>A<br>B")
        line_height = round(pt_to_px(normal.config.handwriting.body_font_pt, normal.dpi) * normal.config.handwriting.line_spacing)
        self.assertEqual(repeated.y - normal.y, line_height)
        self.assertEqual(leading.y - normal.y, line_height)
        self.assertEqual(len(repeated.pages), 1)

    def test_empty_br_paragraph_reserves_a_line(self):
        report = self.render_source("<br>")
        line_height = round(pt_to_px(report.config.handwriting.body_font_pt, report.dpi) * report.config.handwriting.line_spacing)
        self.assertGreaterEqual(report.y - report.margin_top, line_height)

    def test_br_preserves_empty_lines_in_paragraphs_containing_math(self):
        normal = self.render_source("A $x$<br>B")
        repeated = self.render_source("A $x$<br><br>B")
        line_height = round(pt_to_px(normal.config.handwriting.body_font_pt, normal.dpi) * normal.config.handwriting.line_spacing)
        self.assertEqual(repeated.y - normal.y, line_height)

    def test_html_paragraphs_have_the_same_spacing_as_markdown_paragraphs(self):
        html = self.render_source("<p>A</p><p>B</p>")
        markdown = self.render_source("A\n\nB")
        self.assertEqual(html.y, markdown.y)
        self.assertEqual(self.ink_bbox(html.pages[0]), self.ink_bbox(markdown.pages[0]))

    def test_newpage_restarts_content_at_the_top_of_the_next_page(self):
        report = self.render_source("SAME<newpage>SAME")
        self.assertEqual(len(report.pages), 2)
        first = self.ink_bbox(report.pages[0])
        second = self.ink_bbox(report.pages[1])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first, second)

    def test_leading_trailing_and_repeated_page_controls_do_not_add_blank_pages(self):
        cases = (
            ("<newpage>", 1),
            ("<newpage>A", 1),
            ("A<newpage>", 1),
            ("<newpage>A<newpage><newpage>B<newpage>", 2),
            ("A<newpage>B<newpage>C", 3),
        )
        for source, count in cases:
            with self.subTest(source=source):
                report = self.render_source(source)
                self.assertEqual(len(report.pages), count)
                if source != "<newpage>":
                    self.assertTrue(all(self.ink_bbox(page) is not None for page in report.pages))

    def test_paragraph_br_newpage_and_equation_tag_render_together(self):
        source = "<p>A $x=1$<br>B</p>\n<newpage>\n$$\nE=mc^2\\tag{1}\n$$"
        report = self.make_report()
        stderr = StringIO()
        with redirect_stderr(stderr):
            pages = report.render(parse_markdown(source))
        self.assertEqual(len(pages), 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(all(self.ink_bbox(page) is not None for page in pages))

    def test_newpage_before_heading_and_list_keeps_their_content(self):
        report = self.render_source("A\n<newpage>\n# Heading\n\n- Item")
        self.assertEqual(len(report.pages), 2)
        self.assertTrue(all(self.ink_bbox(page) is not None for page in report.pages))

    def test_newpage_after_list_without_a_blank_line_starts_a_second_page(self):
        report = self.render_source("- Item\n<newpage>\n# Next")
        self.assertEqual(len(report.pages), 2)
        self.assertTrue(all(self.ink_bbox(page) is not None for page in report.pages))

    def test_newpage_after_html_image_starts_a_second_page(self):
        report = self.render_source('<img src="x.png" alt="Figure">\n<newpage>\n# Next')
        self.assertEqual(len(report.pages), 2)
        self.assertTrue(all(self.ink_bbox(page) is not None for page in report.pages))

    def test_headings_lists_and_tables_render_br_with_real_handwriting(self):
        source = "# A<br>B\n\n- C<br><br>D\n\n| Header<br>Unit |\n| --- |\n| E<br>F |"
        report = self.render_source(source)
        self.assertEqual(len(report.pages), 1)
        self.assertIsNotNone(self.ink_bbox(report.pages[0]))


if __name__ == "__main__":
    unittest.main()
