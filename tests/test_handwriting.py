import unittest
from pathlib import Path

from handwritten_report.config import HandwritingConfig
from handwritten_report.handwriting import HandwritingEngine, _font_order_key, _load_font


class HandwritingFontTests(unittest.TestCase):
    def test_numbered_fonts_sort_naturally(self):
        candidates = [Path("font/10.ttf"), Path("font/2.ttf"), Path("font/1.ttf")]
        ordered = sorted(candidates, key=_font_order_key)
        self.assertEqual([path.name for path in ordered], ["1.ttf", "2.ttf", "10.ttf"])

    def test_numbered_fonts_form_the_fallback_chain(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        names = [Path(path).name for path in engine.font_paths[:2]]
        self.assertEqual(names, ["1.ttf", "2.ttf"])
        self.assertEqual(Path(engine.fallback_font_path).name, "2.ttf")

    def test_mixed_font_runs_are_shifted_to_a_shared_baseline(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        runs = [(path, "x") for path in engine.font_paths[:2]]
        reference_ascent = engine._reference_ascent(runs, 44)
        for font_path, _ in runs:
            ascent = _load_font(font_path, 44).getmetrics()[0]
            shift = engine._baseline_shift(font_path, 44, reference_ascent)
            self.assertEqual(ascent + shift, reference_ascent)

    def test_horizontal_one_glyph_gets_body_position_adjustment(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        self.assertGreater(engine._glyph_vertical_adjustment("一", 44), 0)
        self.assertEqual(engine._glyph_vertical_adjustment("块", 44), 0)


if __name__ == "__main__":
    unittest.main()
