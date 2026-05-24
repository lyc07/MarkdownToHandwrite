import unittest

from handwritten_report.latex_text import latex_to_hand_text
from handwritten_report.markdown_parser import FormulaBlock, ImageBlock, TableBlock, parse_markdown


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


if __name__ == "__main__":
    unittest.main()
