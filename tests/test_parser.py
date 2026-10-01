import unittest

from markdown_to_handwrite.latex_text import latex_to_hand_text
from markdown_to_handwrite.markdown_parser import (
    CodeBlock,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    parse_markdown,
)


class ParserTests(unittest.TestCase):
    def test_formula_conversion(self):
        self.assertEqual(latex_to_hand_text(r"g=\frac{4\pi^2l}{T^2}"), "g=(4π^2l)/(T^2)")
        self.assertEqual(latex_to_hand_text(r"E=\frac{|g-g_0|}{g_0}\times100\%"), "E=(|g-g_0|)/(g_0)×100%")

    def test_markdown_blocks(self):
        blocks = parse_markdown(
            """
# 标题

公式：

$$
g = \\frac{4\\pi^2l}{T^2}
$$

| A | B |
| - | - |
| 1 | 2 |

![示意图](demo.png)
"""
        )
        formula = next(block for block in blocks if isinstance(block, FormulaBlock))
        self.assertIn(r"\frac", formula.text)
        self.assertTrue(any(isinstance(block, TableBlock) for block in blocks))
        self.assertTrue(any(isinstance(block, ImageBlock) for block in blocks))

    def test_standard_latex_inline_delimiters_become_math_parts(self):
        blocks = parse_markdown(r"位移满足 \(s=v_0t+\frac12at^2\)，且 $t>0$。")
        paragraph = next(block for block in blocks if isinstance(block, ParagraphBlock))
        math_parts = [part.text for part in paragraph.parts if part.kind == "math"]

        self.assertEqual(math_parts, [r"s=v_0t+\frac12at^2", "t>0"])
        self.assertEqual(paragraph.parts[0].text, "位移满足 ")

    def test_escaped_latex_delimiters_remain_literal_text(self):
        blocks = parse_markdown(r"字面量 \\(x+1\\) 不应成为公式。")
        paragraph = next(block for block in blocks if isinstance(block, ParagraphBlock))

        self.assertFalse(any(part.kind == "math" for part in paragraph.parts))

    def test_latex_closer_inside_braced_content_does_not_end_the_formula(self):
        bodies = (
            r"\text{\)}+1",
            r"\frac{1}{\text{a\)}}",
            r"\text{\)}+\{x\}",
            r"\{+1",
            r"\\{\)}+1",
        )
        for body in bodies:
            with self.subTest(body=body):
                blocks = parse_markdown("前" + r"\(" + body + r"\)" + "后")
                paragraph = next(block for block in blocks if isinstance(block, ParagraphBlock))
                self.assertEqual([part.text for part in paragraph.parts if part.kind == "math"], [body])
                self.assertEqual([part.text for part in paragraph.parts if part.kind == "text"], ["前", "后"])

    def test_backslash_parity_distinguishes_escaped_and_real_latex_closers(self):
        for backslashes in (2, 3, 4, 5):
            with self.subTest(backslashes=backslashes):
                source = r"\(x" + "\\" * backslashes + ")y" + r"\)"
                paragraph = next(block for block in parse_markdown(source) if isinstance(block, ParagraphBlock))
                expected = (
                    "x" + "\\" * backslashes + ")y"
                    if backslashes % 2 == 0
                    else "x" + "\\" * (backslashes - 1)
                )
                self.assertEqual([part.text for part in paragraph.parts if part.kind == "math"], [expected])

    def test_missing_brace_preserves_formula_for_the_math_error_handler(self):
        for body in (r"\frac{1}{x", r"\text{abc"):
            with self.subTest(body=body):
                paragraph = next(
                    block for block in parse_markdown(r"\(" + body + r"\)")
                    if isinstance(block, ParagraphBlock)
                )
                self.assertEqual([part.text for part in paragraph.parts if part.kind == "math"], [body])

    def test_parenthesized_math_supports_adjacent_text_and_all_table_cells(self):
        blocks = parse_markdown(
            "前" + r"\(x\)" + "中" + r"\(y+1\)" + "后\n\n"
            + r"| 量\(Q\) | \(H\) |" + "\n| --- | --- |\n"
            + r"| 左\(a\)右\(b\) | \(\frac{c}{d}\) |"
        )
        paragraph = next(block for block in blocks if isinstance(block, ParagraphBlock))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        self.assertEqual([part.text for part in paragraph.parts if part.kind == "math"], ["x", "y+1"])
        self.assertEqual([part.text for part in paragraph.parts if part.kind == "text"], ["前", "中", "后"])
        self.assertEqual(
            [[part.text for part in cell if part.kind == "math"] for cell in table.headers],
            [["Q"], ["H"]],
        )
        self.assertEqual(
            [[part.text for part in cell if part.kind == "math"] for cell in table.rows[0]],
            [["a", "b"], [r"\frac{c}{d}"]],
        )

    def test_parenthesized_math_in_code_or_without_matching_delimiters_stays_literal(self):
        literal = r"\(x+1\)"
        blocks = parse_markdown(f"`{literal}`\n\n```latex\n{literal}\n```\n\n" + r"Unclosed \(x+1")
        body = [block for block in blocks if isinstance(block, ParagraphBlock)]
        self.assertEqual([(part.kind, part.text) for part in body[0].parts], [("code", literal)])
        self.assertFalse(any(part.kind == "math" for block in body for part in block.parts))
        self.assertEqual([block.text for block in blocks if isinstance(block, CodeBlock)], [literal])
        self.assertIn("Unclosed (x+1", "".join(part.text for part in body[-1].parts))
        for source in (r"No opener x\)", r"Empty \( \)", "\\(x\n\ny\\)", r"\(\text{\)}"):
            with self.subTest(source=source):
                blocks = parse_markdown(source)
                self.assertTrue(all(
                    part.kind != "math"
                    for block in blocks if isinstance(block, ParagraphBlock)
                    for part in block.parts
                ))

    def test_inline_latex_is_preserved_in_heading_table_and_list(self):
        blocks = parse_markdown(
            r"""# Energy \(E=mc^2\)

| Quantity | Value |
| --- | --- |
| Speed | $v=\frac{s}{t}$ |

1. Period \(T=2\pi\sqrt{l/g}\)
"""
        )

        heading = next(block for block in blocks if isinstance(block, HeadingBlock))
        table = next(block for block in blocks if isinstance(block, TableBlock))
        sequence = next(block for block in blocks if isinstance(block, ListBlock))

        self.assertEqual([part.text for part in heading.parts if part.kind == "math"], ["E=mc^2"])
        self.assertEqual(
            [part.text for part in table.rows[0][1] if part.kind == "math"],
            [r"v=\frac{s}{t}"],
        )
        self.assertEqual(
            [part.text for part in sequence.items[0] if part.kind == "math"],
            [r"T=2\pi\sqrt{l/g}"],
        )

    def test_html_media_embeds_become_image_placeholders(self):
        blocks = parse_markdown(
            '<img src="figures/device.png" alt="装置示意图">\n\n'
            '<iframe src="plots/result.html" title="拟合结果"></iframe>\n\n'
            '结果见 <video src="media/run.mp4" title="实验过程"></video>。\n'
        )
        images = [block for block in blocks if isinstance(block, ImageBlock)]
        self.assertEqual([block.src for block in images], [
            "figures/device.png",
            "plots/result.html",
            "media/run.mp4",
        ])
        self.assertEqual(images[1].alt, "拟合结果")


if __name__ == "__main__":
    unittest.main()
