import unittest
from dataclasses import asdict
from pathlib import Path

from markdown_to_handwrite.config import ReportConfig, config_from_dict
from markdown_to_handwrite.web import STATIC_ROOT, RenderService, _config_paths, build_bootstrap, schema_paths, validate_config


class WebConfigTests(unittest.TestCase):
    def test_sidebar_schema_covers_every_config_field(self):
        self.assertEqual(schema_paths(), _config_paths(ReportConfig()))

    def test_bootstrap_includes_defaults_assets_and_examples(self):
        bootstrap = build_bootstrap()
        self.assertEqual(bootstrap["config"], asdict(ReportConfig()))
        self.assertTrue(bootstrap["sections"])
        self.assertTrue(bootstrap["assets"]["fonts"])
        self.assertTrue(bootstrap["examples"])

    def test_bootstrap_exposes_base_weight_slider(self):
        bootstrap = build_bootstrap()
        field = next(
            field
            for section in bootstrap["sections"]
            for field in section["fields"]
            if field["path"] == "handwriting.stroke_weight_base_scale"
        )

        self.assertEqual(bootstrap["config"]["handwriting"]["stroke_weight_base_scale"], 1.0)
        self.assertEqual(field["label"], "回退字体基础字重")
        self.assertEqual((field["min"], field["max"], field["step"]), (0.6, 1.6, 0.01))

    def test_bootstrap_exposes_sdt_trajectory_controls(self):
        bootstrap = build_bootstrap()
        fields = {
            field["path"]: field
            for section in bootstrap["sections"]
            for field in section["fields"]
        }

        self.assertTrue(bootstrap["config"]["handwriting"]["sdt_trajectory_enabled"])
        self.assertEqual(bootstrap["config"]["handwriting"]["sdt_stroke_width"], 16.0)
        self.assertEqual(fields["handwriting.sdt_stroke_width"]["label"], "统一基础笔宽")
        self.assertEqual(fields["handwriting.sdt_stroke_width"]["unit"], "SDT")

    def test_bootstrap_exposes_one_gaussian_weight_control(self):
        bootstrap = build_bootstrap()
        paths = {
            field["path"]: field
            for section in bootstrap["sections"]
            for field in section["fields"]
        }

        field = paths["handwriting.stroke_weight_variation_sigma_ratio"]
        self.assertEqual(field["label"], "整体粗细扰动 σ")
        self.assertEqual(field["unit"], "em")
        self.assertNotIn("handwriting.stroke_weight_variation_ratio", paths)
        self.assertNotIn("handwriting.stroke_weight_variation_probability", paths)

    def test_natural_preset_is_the_current_default_style(self):
        bootstrap = build_bootstrap()
        natural = bootstrap["presets"]["natural"]

        for path, value in natural.items():
            section, field = path.split(".")
            self.assertEqual(value, bootstrap["config"][section][field], path)

    def test_formal_and_casual_presets_bracket_natural_disturbance(self):
        presets = build_bootstrap()["presets"]
        increasing = {
            "handwriting.perturb_theta_sigma",
            "handwriting.math_perturb_y_sigma_ratio",
            "handwriting.sdt_coordinate_jitter",
            "handwriting.elastic_strength_ratio",
            "handwriting.baseline_wave_amplitude_ratio",
            "handwriting.math_rule_tilt_ratio",
            "handwriting.math_rule_wobble_ratio",
            "handwriting.math_rule_jitter_ratio",
            "handwriting.sdt_width_jitter",
            "handwriting.sdt_taper",
            "handwriting.stroke_weight_variation_sigma_ratio",
            "handwriting.ink_density_jitter",
            "handwriting.dry_brush_probability",
        }

        for path in increasing:
            self.assertLess(presets["formal"][path], presets["natural"][path], path)
            self.assertLess(presets["natural"][path], presets["casual"][path], path)

        for path in {
            "handwriting.sdt_jitter_correlation",
            "handwriting.elastic_smoothness_ratio",
            "handwriting.baseline_wave_length_em",
            "handwriting.dry_brush_min_opacity",
        }:
            self.assertGreater(presets["formal"][path], presets["natural"][path], path)
            self.assertGreater(presets["natural"][path], presets["casual"][path], path)

    def test_preset_buttons_have_no_secondary_labels(self):
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("<small>", html)
        self.assertNotIn("克制", html)
        self.assertNotIn("推荐", html)
        self.assertNotIn("明显", html)

    def test_body_recomputes_text_color_inside_the_active_theme(self):
        css = (STATIC_ROOT / "styles.css").read_text(encoding="utf-8")

        self.assertIn("body { color: var(--ink); }", css)

    def test_legacy_weight_probability_and_amplitude_migrate_to_sigma(self):
        config = config_from_dict(
            {
                "handwriting": {
                    "stroke_weight_variation_ratio": 0.012,
                    "stroke_weight_variation_probability": 0.22,
                }
            }
        )

        expected = 0.012 * (0.22 / 3.0) ** 0.5
        self.assertAlmostEqual(config.handwriting.stroke_weight_variation_sigma_ratio, expected)

    def test_sidebar_groups_parameters_by_single_responsibility(self):
        sections = {section["id"]: section for section in build_bootstrap()["sections"]}
        paths = {
            section_id: {field["path"] for field in section["fields"]}
            for section_id, section in sections.items()
        }

        self.assertIn("handwriting.sdt_stroke_width", paths["sdt-trajectories"])
        self.assertIn("handwriting.sdt_coordinate_jitter", paths["first-layer"])
        self.assertIn("handwriting.elastic_strength_ratio", paths["first-layer"])
        self.assertIn("handwriting.math_rule_jitter_ratio", paths["first-layer"])
        self.assertIn("handwriting.math_perturb_y_sigma_ratio", paths["first-layer"])
        self.assertIn("handwriting.sdt_width_jitter", paths["second-layer"])
        self.assertIn("handwriting.ink_color", paths["second-layer"])
        self.assertIn("layout.show_page_numbers", paths["footer"])
        self.assertIn("layout.footer_gap_mm", paths["footer"])

    def test_config_from_dict_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "Unknown config field"):
            config_from_dict({"handwriting": {"imaginary_slider": 1}})

    def test_validation_rejects_impossible_margins(self):
        config = ReportConfig()
        config.page.margin_left_mm = 120
        config.page.margin_right_mm = 120
        with self.assertRaisesRegex(ValueError, "左右边距"):
            validate_config(config)

    def test_validation_rejects_extreme_base_weight(self):
        config = ReportConfig()
        config.handwriting.stroke_weight_base_scale = 4.0
        with self.assertRaisesRegex(ValueError, "基础字重倍率"):
            validate_config(config)

    def test_validation_rejects_extreme_formula_vertical_jitter(self):
        config = ReportConfig()
        config.handwriting.math_perturb_y_sigma_ratio = 0.5
        with self.assertRaisesRegex(ValueError, "公式字符垂直偏移"):
            validate_config(config)

    def test_render_service_creates_preview_and_pdf(self):
        config = asdict(ReportConfig())
        config["page"].update({"dpi": 96, "margin_top_mm": 18})
        config["background"].update({"style": "plain", "auto_discover": False})
        config["handwriting"].update({"body_font_pt": 11, "second_layer_enabled": False})
        output_root = Path("output/webui-test")
        result = RenderService(output_root).render("# 测试\n\n这是 WebUI 预览。", config)
        self.assertEqual(result["pageCount"], 1)
        job_root = output_root / result["jobId"]
        self.assertTrue((job_root / "markdown-to-handwrite.pdf").is_file())
        self.assertTrue((job_root / "page-1.webp").is_file())


if __name__ == "__main__":
    unittest.main()
