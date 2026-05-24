import unittest

from handwritten_report.markdown_parser import InlinePart, parts_to_text
from handwritten_report.typography import westernize_punctuation


class TypographyTests(unittest.TestCase):
    def test_westernizes_chinese_punctuation(self):
        self.assertEqual(
            westernize_punctuation("结果为：9.79，与标准值接近。误差（约为 1％）；“合格”！"),
            '结果为:9.79,与标准值接近.误差(约为 1%);"合格"!',
        )
        self.assertEqual(westernize_punctuation("数据、公式……结论——一致"), "数据,公式...结论--一致")
        self.assertEqual(westernize_punctuation("a·b，c"), "a·b,c")

    def test_visible_markdown_text_is_normalized(self):
        text = parts_to_text([InlinePart("text", "取平均值："), InlinePart("text", "有效。")])
        self.assertEqual(text, "取平均值:有效.")


if __name__ == "__main__":
    unittest.main()
