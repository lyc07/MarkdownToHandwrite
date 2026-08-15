import random
import math
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from markdown_to_handwrite.config import HandwritingConfig
from markdown_to_handwrite.handwriting import (
    HandwritingEngine,
    _adjust_stroke_weight,
    _estimate_optical_stroke_weight,
    _font_order_key,
    _local_font_candidates,
    _load_font,
    _warp_ink_mask,
    starts_with_forbidden_line_punctuation,
    wrap_text,
)
from markdown_to_handwrite.sdt_renderer import (
    BUNDLED_TRAJECTORIES,
    SdtTrajectoryStore,
    _resample_stroke,
    coordinates_to_strokes,
)
from markdown_to_handwrite.typography import westernize_punctuation


class HandwritingFontTests(unittest.TestCase):
    def test_bundled_sdt_store_loads_chinese_trajectories(self):
        store = SdtTrajectoryStore()

        self.assertTrue(BUNDLED_TRAJECTORIES.is_file())
        self.assertTrue(store.contains("中"))
        self.assertFalse(store.contains("x"))
        strokes = store.load("中")
        self.assertIsNotNone(strokes)
        self.assertTrue(all(stroke.shape[1] == 2 for stroke in strokes))

    def test_sdt_pen_width_is_shared_across_text_and_math_sizes(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                sdt_stroke_width=14,
                stroke_weight_base_scale=1.0,
            ),
            reference_size_px=34,
            math_reference_size_px=55,
        )

        self.assertTrue(engine.uses_sdt_trajectories)
        self.assertAlmostEqual(engine.uniform_pen_width_px(), 14 * 34 / 256)
        text = engine.render_line("中文", 34, 300, seed_extra="shared-width")
        math = engine.render_line("x+1=α", 55, 300, seed_extra="shared-width", math=True)
        self.assertIsNotNone(text.getchannel("A").getbbox())
        self.assertIsNotNone(math.getchannel("A").getbbox())

    def test_sdt_pen_width_has_one_controller(self):
        light_legacy_scale = HandwritingEngine(
            HandwritingConfig(sdt_stroke_width=14, stroke_weight_base_scale=0.7),
            reference_size_px=40,
        )
        heavy_legacy_scale = HandwritingEngine(
            HandwritingConfig(sdt_stroke_width=14, stroke_weight_base_scale=1.4),
            reference_size_px=40,
        )

        expected = 14 * 40 / 256
        self.assertAlmostEqual(light_legacy_scale.uniform_pen_width_px(), expected)
        self.assertAlmostEqual(heavy_legacy_scale.uniform_pen_width_px(), expected)

        widths = [
            HandwritingEngine(
                HandwritingConfig(sdt_stroke_width=value),
                reference_size_px=40,
            ).uniform_pen_width_px()
            for value in (12, 14, 16)
        ]
        self.assertLess(widths[0], widths[1])
        self.assertLess(widths[1], widths[2])

    def test_rotation_uses_the_same_radian_conversion_in_sdt_mode(self):
        config = HandwritingConfig(perturb_theta_sigma=0.008)
        engine = HandwritingEngine(config)

        self.assertAlmostEqual(
            engine._trajectory_style().rotation_sigma_deg,
            math.degrees(config.perturb_theta_sigma),
        )

    def test_formula_vertical_jitter_uses_its_own_font_relative_sigma(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                perturb_y_sigma_px=7.0,
                math_perturb_y_sigma_ratio=0.02,
            )
        )

        self.assertEqual(engine._vertical_position_sigma(40, math_mode=False), 7.0)
        self.assertEqual(engine._vertical_position_sigma(40, math_mode=True), 0.8)
        self.assertEqual(engine._vertical_position_sigma(20, math_mode=True), 0.4)

    def test_character_position_samples_are_gaussian_and_three_sigma_bounded(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        sigma = 2.0
        samples = [
            engine._sample_position_offset(random.Random(seed), sigma)
            for seed in range(2000)
        ]

        self.assertTrue(any(value < 0 for value in samples))
        self.assertTrue(any(value > 0 for value in samples))
        self.assertAlmostEqual(sum(samples) / len(samples), 0.0, delta=0.15)
        self.assertTrue(all(abs(value) <= 3 * sigma for value in samples))
        self.assertEqual(engine._sample_position_offset(random.Random(1), 0), 0)

    def test_character_position_padding_covers_every_accepted_offset(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))

        self.assertEqual(engine._position_jitter_padding(3.0, 12.0), 40)
        self.assertGreaterEqual(engine._position_jitter_padding(0.0, 0.0), 8)

    def test_arc_length_resampling_removes_source_point_density_difference(self):
        sparse = np.array([[0, 0], [100, 0]], dtype=np.float32)
        dense = np.stack((np.linspace(0, 100, 51), np.zeros(51)), axis=1).astype(np.float32)

        sparse_result = _resample_stroke(sparse, spacing=5)
        dense_result = _resample_stroke(dense, spacing=5)

        self.assertEqual(sparse_result.shape, dense_result.shape)
        np.testing.assert_allclose(sparse_result, dense_result, atol=1e-5)

    def test_sdt_rendering_is_reproducible_and_pen_width_changes_ink_area(self):
        thin = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                second_layer_enabled=False,
                sdt_stroke_width=10,
            ),
            reference_size_px=40,
        )
        thick = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                second_layer_enabled=False,
                sdt_stroke_width=18,
            ),
            reference_size_px=40,
        )

        first = thin.render_line("轨迹", 40, 300, seed_extra="same")
        repeated = thin.render_line("轨迹", 40, 300, seed_extra="same")
        different = thin.render_line("轨迹", 40, 300, seed_extra="different")
        heavier = thick.render_line("轨迹", 40, 300, seed_extra="same")

        self.assertEqual((first.size, first.tobytes()), (repeated.size, repeated.tobytes()))
        self.assertNotEqual((first.size, first.tobytes()), (different.size, different.tobytes()))
        self.assertGreater(sum(heavier.getchannel("A").getdata()), sum(first.getchannel("A").getdata()))

    def test_sdt_coordinate_conversion_respects_pen_breaks(self):
        coordinates = np.array(
            [
                [1, 2, 1, 0, 0],
                [3, 4, 0, 1, 0],
                [5, 6, 1, 0, 0],
                [7, 8, 0, 1, 0],
                [0, 0, 0, 0, 1],
            ],
            dtype=np.float32,
        )

        strokes = coordinates_to_strokes(coordinates)

        self.assertEqual(len(strokes), 2)
        self.assertEqual(strokes[0].tolist(), [[1.0, 2.0], [4.0, 6.0]])
        self.assertEqual(strokes[1].tolist(), [[9.0, 12.0], [16.0, 20.0]])

    def test_numbered_fonts_sort_naturally(self):
        candidates = [Path("font/10.ttf"), Path("font/2.ttf"), Path("font/1.ttf")]
        ordered = sorted(candidates, key=_font_order_key)
        self.assertEqual([path.name for path in ordered], ["1.ttf", "2.ttf", "10.ttf"])

    def test_available_fonts_form_a_valid_fallback_chain(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        paths = [Path(path) for path in engine.font_paths[:2]]
        self.assertEqual(paths[0].resolve(), _local_font_candidates()[0].resolve())
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertNotEqual(paths[0], paths[1])
        self.assertEqual(Path(engine.fallback_font_path), paths[1])

    def test_mixed_font_runs_are_shifted_to_a_shared_baseline(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        runs = [(path, "x") for path in engine.font_paths[:2]]
        reference_ascent = engine._reference_ascent(runs, 44)
        for font_path, _ in runs:
            ascent = _load_font(font_path, 44).getmetrics()[0]
            shift = engine._baseline_shift(font_path, 44, reference_ascent)
            self.assertEqual(ascent + shift, reference_ascent)

    def test_sdt_mixed_font_formula_glyphs_keep_the_shared_baseline(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                second_layer_enabled=False,
                perturb_theta_sigma=0.0,
                math_perturb_y_sigma_ratio=0.0,
                sdt_coordinate_jitter=0.0,
                sdt_width_jitter=0.0,
            )
        )
        self.assertTrue(engine.uses_sdt_trajectories)

        left, left_baseline = engine.render_line("|u", 55, 500, math=True, return_baseline=True)
        right, right_baseline = engine.render_line(")|", 55, 500, math=True, return_baseline=True)
        u_bbox = left.crop((left.width // 2, 0, left.width, left.height)).getchannel("A").getbbox()
        paren_bbox = right.crop((0, 0, right.width // 2, right.height)).getchannel("A").getbbox()

        self.assertIsNotNone(u_bbox)
        self.assertIsNotNone(paren_bbox)
        self.assertLessEqual(abs(u_bbox[3] - left_baseline), 2)
        self.assertGreaterEqual(paren_bbox[3], right_baseline + 3)
        self.assertEqual(left_baseline, right_baseline)

    def test_horizontal_one_glyph_is_not_pushed_below_the_body_center(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        self.assertEqual(engine._glyph_vertical_adjustment("一", 44), 0)
        self.assertEqual(engine._glyph_vertical_adjustment("块", 44), 0)

    def test_wrapped_lines_keep_closing_punctuation_on_previous_line(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        text = westernize_punctuation("甲乙，丙丁。戊己）庚辛；终点。”")
        width = round(engine.measure("甲乙", 32))
        lines = wrap_text(engine, text, 32, width)
        self.assertTrue(any(line.endswith(",") for line in lines))
        self.assertTrue(any(line.endswith(".") for line in lines))
        self.assertTrue(any(line.endswith('."') for line in lines))
        self.assertTrue(all(not starts_with_forbidden_line_punctuation(line) for line in lines[1:]))

    def test_second_layer_is_deterministic_for_the_same_seed(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                elastic_strength_ratio=0.08,
                baseline_wave_amplitude_ratio=0.05,
                stroke_weight_variation_sigma_ratio=0.02,
                ink_density_jitter=0.2,
                dry_brush_probability=1.0,
            )
        )
        source = Image.new("RGBA", (180, 60), (0, 0, 0, 0))
        draw = ImageDraw.Draw(source)
        draw.line((18, 16, 160, 16), fill=engine.ink, width=4)
        draw.line((28, 10, 28, 50), fill=engine.ink, width=5)

        first = engine._apply_second_layer(source, 40, seed=1234)
        repeated = engine._apply_second_layer(source, 40, seed=1234)
        different = engine._apply_second_layer(source, 40, seed=4321)

        self.assertEqual((first.size, first.tobytes()), (repeated.size, repeated.tobytes()))
        self.assertNotEqual((first.size, first.tobytes()), (different.size, different.tobytes()))

    def test_second_layer_can_be_disabled_without_modifying_the_image(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False, second_layer_enabled=False))
        source = Image.new("RGBA", (30, 20), engine.ink)

        result = engine._apply_second_layer(source, 32, seed=10)

        self.assertIs(result, source)

    def test_heading_sizes_are_thinned_toward_body_weight(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                stroke_weight_variation_sigma_ratio=0.0,
            ),
            reference_size_px=34,
        )

        body = engine._render_with_pillow("重力加速度测量实验", 34, 800, seed=7)
        heading = engine._render_with_pillow("重力加速度测量实验", 55, 800, seed=7)
        body_target = engine._reference_weight_for_text("重力加速度测量实验", 34)
        heading_target = engine._reference_weight_for_text("重力加速度测量实验", 55)
        body_adjustment = engine._base_stroke_weight_adjustment(
            body.getchannel("A"),
            reference_weight=body_target,
        )
        heading_adjustment = engine._base_stroke_weight_adjustment(
            heading.getchannel("A"),
            reference_weight=heading_target,
        )

        self.assertGreater(body_adjustment, 0.0)
        self.assertLess(heading_adjustment, 0.0)
        self.assertLess(abs(body_adjustment), 0.35)
        self.assertLess(abs(heading_adjustment), 0.5)

    def test_random_weight_variation_is_gaussian_signed_and_size_independent(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                stroke_weight_variation_sigma_ratio=0.02,
            ),
            reference_size_px=40,
        )
        sigma = engine._random_stroke_weight_sigma()
        variations = [
            engine._random_stroke_weight_adjustment(random.Random(seed), sigma)
            for seed in range(2000)
        ]

        self.assertEqual(sigma, 0.4)
        self.assertTrue(any(value < 0 for value in variations))
        self.assertTrue(any(value > 0 for value in variations))
        self.assertAlmostEqual(sum(variations) / len(variations), 0.0, delta=0.03)
        self.assertAlmostEqual(np.std(variations), sigma, delta=0.03)
        self.assertTrue(all(abs(value) <= 3 * sigma for value in variations))

    def test_base_weight_scale_moves_the_optical_target(self):
        source = Image.new("L", (40, 24), 0)
        draw = ImageDraw.Draw(source)
        draw.rectangle((8, 8, 31, 15), fill=255)
        reference_weight = _estimate_optical_stroke_weight(source)
        light_engine = HandwritingEngine(
            HandwritingConfig(prefer_handright=False, stroke_weight_base_scale=0.8)
        )
        heavy_engine = HandwritingEngine(
            HandwritingConfig(prefer_handright=False, stroke_weight_base_scale=1.2)
        )

        light_adjustment = light_engine._base_stroke_weight_adjustment(
            source,
            reference_weight=reference_weight,
        )
        heavy_adjustment = heavy_engine._base_stroke_weight_adjustment(
            source,
            reference_weight=reference_weight,
        )

        self.assertLess(light_adjustment, 0.0)
        self.assertGreater(heavy_adjustment, 0.0)

    def test_sdt_math_and_text_share_weight_variation_reference(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                stroke_weight_variation_sigma_ratio=0.02,
            ),
            reference_size_px=40,
            math_reference_size_px=50,
        )
        math_flags: list[bool] = []
        original = engine._apply_second_layer

        def capture(image, size_px, seed, math_mode=False, **kwargs):
            math_flags.append(math_mode)
            return original(image, size_px, seed, math_mode=math_mode, **kwargs)

        engine._apply_second_layer = capture
        engine.render_line("x+1", 36, 500, math=True)

        self.assertEqual(math_flags, [True])
        self.assertEqual(engine._random_stroke_weight_sigma(), 0.4)
        self.assertEqual(engine._random_stroke_weight_sigma(math_mode=True), 0.4)

        fallback = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                sdt_trajectory_enabled=False,
                stroke_weight_variation_sigma_ratio=0.02,
            ),
            reference_size_px=40,
            math_reference_size_px=50,
        )
        self.assertEqual(fallback._random_stroke_weight_sigma(math_mode=True), 0.5)

    def test_optical_weight_detects_small_antialiased_math_as_lighter(self):
        engine = HandwritingEngine(
            HandwritingConfig(prefer_handright=False),
            reference_size_px=34,
            math_reference_size_px=35,
        )
        small = engine._render_with_pillow("x", 18, 200, seed=7, math=True)
        reference = engine._render_with_pillow("x", 35, 200, seed=7, math=True)

        self.assertLess(
            _estimate_optical_stroke_weight(small.getchannel("A")),
            _estimate_optical_stroke_weight(reference.getchannel("A")),
        )
        target = engine._reference_weight_for_text("x", 18, math_mode=True)
        self.assertGreater(
            engine._base_stroke_weight_adjustment(
                small.getchannel("A"),
                math_mode=True,
                reference_weight=target,
            ),
            0.05,
        )

    def test_weight_normalization_runs_after_geometric_resampling(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                elastic_strength_ratio=0.08,
                baseline_wave_amplitude_ratio=0.04,
                stroke_weight_variation_sigma_ratio=0.0,
                ink_density_jitter=0.0,
                dry_brush_probability=0.0,
            ),
            reference_size_px=34,
            math_reference_size_px=35,
        )
        source = engine._render_with_pillow("x", 18, 200, seed=7, math=True)
        target = engine._reference_weight_for_text("x", 18, math_mode=True)
        result = engine._apply_second_layer(
            source,
            18,
            seed=17,
            math_mode=True,
            reference_weight=target,
        )

        pad = 8
        padded = Image.new("L", (source.width + 2 * pad, source.height + 2 * pad), 0)
        padded.paste(source.getchannel("A"), (pad, pad))
        warped = _warp_ink_mask(
            padded,
            random.Random(17),
            elastic_strength=18 * 0.08,
            elastic_smoothness=max(2.0, 18 * engine.config.elastic_smoothness_ratio),
            baseline_amplitude=18 * 0.04,
            baseline_wavelength=max(2.0, 18 * engine.config.baseline_wave_length_em),
        )
        warped_error = abs(_estimate_optical_stroke_weight(warped) - target)
        result_error = abs(_estimate_optical_stroke_weight(result.getchannel("A")) - target)
        self.assertLess(result_error, warped_error)

    def test_subpixel_weight_adjustment_can_thicken_and_thin(self):
        source = Image.new("L", (40, 24), 0)
        draw = ImageDraw.Draw(source)
        draw.rectangle((8, 8, 31, 15), fill=255)

        thinner = _adjust_stroke_weight(source, -0.65)
        thicker = _adjust_stroke_weight(source, 0.65)

        self.assertLess(sum(thinner.getdata()), sum(source.getdata()))
        self.assertGreater(sum(thicker.getdata()), sum(source.getdata()))


if __name__ == "__main__":
    unittest.main()
