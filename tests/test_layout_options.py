import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from markdown_to_handwrite import cli
from markdown_to_handwrite.config import ReportConfig, config_from_dict, load_config
from markdown_to_handwrite.web import build_bootstrap, validate_config


class LayoutOptionConfigTests(unittest.TestCase):
    def test_defaults_keep_previous_spacing_and_enable_justification(self):
        config = ReportConfig()
        self.assertEqual(config.handwriting.word_spacing_px, -1.0)
        self.assertEqual(config.handwriting.advance_jitter_sigma_ratio, 0.01)
        self.assertTrue(config.layout.justify_paragraphs)

    def test_decimal_spacing_and_disabled_jitter_survive_json_round_trip(self):
        data = {
            "handwriting": {"word_spacing_px": 0.5, "advance_jitter_sigma_ratio": 0},
            "layout": {"justify_paragraphs": False},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_config(path)
        restored = config_from_dict(json.loads(json.dumps(asdict(loaded))))
        self.assertEqual(restored.handwriting.word_spacing_px, 0.5)
        self.assertEqual(restored.handwriting.advance_jitter_sigma_ratio, 0)
        self.assertFalse(restored.layout.justify_paragraphs)

    def test_legacy_integer_spacing_preserves_new_option_defaults(self):
        config = config_from_dict({"handwriting": {"word_spacing_px": -2}})
        self.assertEqual(config.handwriting.word_spacing_px, -2)
        self.assertEqual(config.handwriting.advance_jitter_sigma_ratio, 0.01)
        self.assertTrue(config.layout.justify_paragraphs)

    def test_spacing_and_jitter_accept_inclusive_boundaries(self):
        for spacing, jitter in ((-12, 0), (24, 0.1), (0.5, 0.025)):
            with self.subTest(spacing=spacing, jitter=jitter):
                config = config_from_dict({"handwriting": {
                    "word_spacing_px": spacing,
                    "advance_jitter_sigma_ratio": jitter,
                }})
                validate_config(config)

    def test_spacing_rejects_out_of_range_non_numeric_and_non_finite_values(self):
        for value in (-12.5, 24.5, "0.5", None, True, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "字符间距"):
                    config_from_dict({"handwriting": {"word_spacing_px": value}})

    def test_jitter_rejects_out_of_range_non_numeric_and_non_finite_values(self):
        for value in (-0.001, 0.101, "0.01", None, False, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "字距随机扰动"):
                    config_from_dict({"handwriting": {"advance_jitter_sigma_ratio": value}})

    def test_justification_requires_a_real_boolean(self):
        for value in (0, 1, "false", "true", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "布尔值"):
                    config_from_dict({"layout": {"justify_paragraphs": value}})

    def test_file_loading_and_web_validation_share_spacing_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"handwriting": {"word_spacing_px": 25}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "字符间距"):
                load_config(path)
        config = ReportConfig()
        config.layout.justify_paragraphs = "false"
        with self.assertRaisesRegex(ValueError, "布尔值"):
            validate_config(config)

    def test_bootstrap_exposes_spacing_jitter_and_justification_controls(self):
        bootstrap = build_bootstrap()
        fields = {
            field["path"]: field
            for section in bootstrap["sections"]
            for field in section["fields"]
        }
        spacing = fields["handwriting.word_spacing_px"]
        self.assertEqual(spacing["label"], "字符间距")
        self.assertEqual((spacing["min"], spacing["max"], spacing["step"]), (-12, 24, 0.5))
        self.assertEqual(spacing["unit"], "px")
        jitter = fields["handwriting.advance_jitter_sigma_ratio"]
        self.assertEqual(jitter["label"], "字距随机扰动 σ")
        self.assertEqual((jitter["min"], jitter["max"]), (0, 0.1))
        self.assertEqual(jitter["unit"], "em")
        justification = fields["layout.justify_paragraphs"]
        self.assertEqual(justification["label"], "拉伸至右侧对齐")
        self.assertEqual(justification["control"], "toggle")
        self.assertEqual(bootstrap["config"]["handwriting"]["advance_jitter_sigma_ratio"], 0.01)
        self.assertTrue(bootstrap["config"]["layout"]["justify_paragraphs"])


class LayoutOptionCliTests(unittest.TestCase):
    def run_cli_with_config(self, data, *options):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.md"
            source.write_text("Sample", encoding="utf-8")
            config_path = root / "config.json"
            config_path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(cli, "ReportRenderer") as renderer_class:
                renderer = renderer_class.return_value
                renderer.render.return_value = [object()]
                renderer.save_pdf.return_value = root / "report.pdf"
                renderer.engine.uses_sdt_trajectories = False
                renderer.engine.handright_available = False
                renderer.engine.font_paths = ["test-font.ttf"]
                with redirect_stdout(StringIO()):
                    result = cli.main([str(source), "--config", str(config_path), *options])
                self.assertEqual(result, 0)
                return renderer_class.call_args.args[0]

    def test_absent_cli_options_do_not_override_json_values(self):
        args = cli.build_parser().parse_args(["input.md"])
        self.assertIsNone(args.char_spacing)
        self.assertIsNone(args.spacing_jitter)
        self.assertIsNone(args.justify)
        config = self.run_cli_with_config({
            "handwriting": {"word_spacing_px": 2.5, "advance_jitter_sigma_ratio": 0.04},
            "layout": {"justify_paragraphs": False},
        })
        self.assertEqual(config.handwriting.word_spacing_px, 2.5)
        self.assertEqual(config.handwriting.advance_jitter_sigma_ratio, 0.04)
        self.assertFalse(config.layout.justify_paragraphs)

    def test_cli_overrides_decimal_spacing_zero_jitter_and_disables_justification(self):
        config = self.run_cli_with_config(
            {"layout": {"justify_paragraphs": True}},
            "--char-spacing", "0.5", "--spacing-jitter", "0", "--no-justify",
        )
        self.assertEqual(config.handwriting.word_spacing_px, 0.5)
        self.assertEqual(config.handwriting.advance_jitter_sigma_ratio, 0)
        self.assertFalse(config.layout.justify_paragraphs)

    def test_cli_can_enable_justification_and_apply_zero_spacing(self):
        config = self.run_cli_with_config(
            {"layout": {"justify_paragraphs": False}}, "--justify", "--char-spacing", "0",
        )
        self.assertTrue(config.layout.justify_paragraphs)
        self.assertEqual(config.handwriting.word_spacing_px, 0)

    def test_invalid_cli_spacing_is_rejected_before_reading_or_rendering(self):
        for options in (
            ["--char-spacing", "25"],
            ["--char-spacing", "nan"],
            ["--spacing-jitter", "-0.01"],
            ["--spacing-jitter", "0.2"],
        ):
            with self.subTest(options=options):
                with patch.object(cli, "ReportRenderer") as renderer_class:
                    with redirect_stderr(StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            cli.main(["not-read.md", *options])
                    self.assertEqual(error.exception.code, 2)
                    renderer_class.assert_not_called()

    def test_justify_and_no_justify_are_mutually_exclusive(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as error:
                cli.build_parser().parse_args(["input.md", "--justify", "--no-justify"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
