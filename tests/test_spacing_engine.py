import math
import random
import unittest

from markdown_to_handwrite.config import HandwritingConfig
from markdown_to_handwrite.handwriting import (
    HandwritingEngine,
    starts_with_forbidden_line_punctuation,
    wrap_text,
)


class CharacterSpacingTests(unittest.TestCase):
    def engine(self, spacing=0.0):
        return HandwritingEngine(
            HandwritingConfig(
                word_spacing_px=spacing,
                advance_jitter_sigma_ratio=0.0,
                perturb_x_sigma_px=0.0,
                perturb_y_sigma_px=0.0,
                perturb_theta_sigma=0.0,
                second_layer_enabled=False,
                sdt_coordinate_jitter=0.0,
                sdt_width_jitter=0.0,
                sdt_taper=0.0,
            )
        )

    def test_nominal_width_includes_each_gap_but_no_trailing_gap(self):
        plain = self.engine()
        spaced = self.engine(7.5)
        tight = self.engine(-2.0)
        for text in ("甲乙丙丁", "AVWA", "甲A乙B"):
            with self.subTest(text=text):
                self.assertAlmostEqual(spaced.measure(text, 40) - plain.measure(text, 40), 22.5)
                self.assertAlmostEqual(tight.measure(text, 40) - plain.measure(text, 40), -6.0)
        self.assertEqual(spaced.measure("甲", 40), plain.measure("甲", 40))
        self.assertEqual(spaced.measure("", 40), 0)

    def test_spaces_keep_their_minimum_width_without_extra_spacing(self):
        engine = self.engine(8)
        space = engine.character_advance(" ", 40)
        self.assertGreaterEqual(space, 14)
        self.assertEqual(space, engine.character_advance(" ", 40, include_spacing=False))
        self.assertAlmostEqual(
            engine.measure("A A", 40),
            engine.measure("A", 40) * 2 + 8 + space,
        )

    def test_extreme_negative_spacing_never_reverses_character_order(self):
        engine = self.engine(-1000)
        self.assertEqual(engine.character_advance("A", 40), 1)
        self.assertEqual(engine._sample_character_advance("A", 40, random.Random(1)), 1)
        self.assertEqual(engine.measure("AAAA", 40), engine.measure("A", 40) + 3)

    def test_advance_jitter_can_be_disabled_independently(self):
        engine = self.engine()
        self.assertEqual(engine._advance_jitter_sigma(40), 0)
        engine.config.advance_jitter_sigma_ratio = 0.025
        self.assertEqual(engine._advance_jitter_sigma(40), 1)

    def test_positive_spacing_cannot_clip_tail_in_any_backend(self):
        engine = self.engine(24)
        renderers = [engine._render_with_pillow, engine._render_with_trajectories]
        if engine.handright_available:
            renderers.append(engine._render_with_handright)
        for render in renderers:
            with self.subTest(backend=render.__name__):
                narrow = render("甲A乙B甲A乙B", 40, 30, 123)
                wide = render("甲A乙B甲A乙B", 40, 2000, 123)
                self.assertIsNotNone(narrow.getchannel("A").getbbox())
                self.assertEqual((narrow.size, narrow.tobytes()), (wide.size, wide.tobytes()))
                self.assertGreater(narrow.width, 300)

    def test_rendered_spacing_matches_nominal_gap_change(self):
        plain = self.engine()
        spaced = self.engine(9)
        for backend in ("_render_with_pillow", "_render_with_trajectories", "_render_with_handright"):
            if backend == "_render_with_handright" and not plain.handright_available:
                continue
            with self.subTest(backend=backend):
                narrow = getattr(plain, backend)("AAAA", 40, 500, 123)
                wide = getattr(spaced, backend)("AAAA", 40, 500, 123)
                self.assertAlmostEqual(wide.width - narrow.width, 27, delta=1)

    def test_first_line_width_does_not_shrink_following_lines(self):
        engine = self.engine()
        lines = wrap_text(
            engine, "甲乙丙丁戊己庚辛", 40,
            math.ceil(engine.measure("甲乙丙丁", 40)),
            first_line_width=math.ceil(engine.measure("甲乙", 40)),
        )
        self.assertEqual(lines, ["甲乙", "丙丁戊己", "庚辛"])

    def test_long_ascii_word_splits_without_loss_or_overflow(self):
        engine = self.engine(4)
        text = "Supercalifragilisticexpialidocious_0123456789"
        width = math.ceil(engine.measure("Super", 40))
        lines = wrap_text(engine, text, 40, width)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(engine.measure(line, 40) <= width for line in lines))

    def test_closing_punctuation_moves_with_preceding_character(self):
        engine = self.engine()
        text = '甲乙,丙丁。戊己)庚辛;终点."'
        width = math.ceil(engine.measure("甲乙", 40))
        lines = wrap_text(engine, text, 40, width)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(not starts_with_forbidden_line_punctuation(line) for line in lines))
        self.assertTrue(all(engine.measure(line, 40) <= width for line in lines))

    def test_unavoidably_wide_single_cluster_is_preserved(self):
        engine = self.engine()
        self.assertEqual(wrap_text(engine, "甲,乙", 40, 1), ["甲,", "乙"])


if __name__ == "__main__":
    unittest.main()
