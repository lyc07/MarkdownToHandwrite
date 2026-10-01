import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from markdown_to_handwrite.config import ReportConfig, config_from_dict, load_config
from markdown_to_handwrite.markdown_parser import ImageBlock, parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer
from markdown_to_handwrite.web import build_bootstrap, validate_config


class FigureNumberingConfigTests(unittest.TestCase):
    def test_numbering_defaults_to_false_for_new_and_existing_configs(self):
        self.assertIs(ReportConfig().layout.number_figures, False)
        self.assertIs(config_from_dict({"layout": {"first_line_indent_em": 2}}).layout.number_figures, False)

    def test_json_file_and_dictionary_round_trip_preserve_both_boolean_values(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "config.json"
                path.write_text(json.dumps({"layout": {"number_figures": enabled}}), encoding="utf-8")
                loaded = load_config(path)
                restored = config_from_dict(json.loads(json.dumps(asdict(loaded))))
                self.assertIs(loaded.layout.number_figures, enabled)
                self.assertIs(restored.layout.number_figures, enabled)
                validate_config(restored)

    def test_config_and_web_validation_require_a_real_boolean(self):
        for value in (0, 1, "false", "true", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "布尔值"):
                    config_from_dict({"layout": {"number_figures": value}})
                config = ReportConfig()
                config.layout.number_figures = value
                with self.assertRaisesRegex(ValueError, "布尔值"):
                    validate_config(config)

    def test_web_bootstrap_exposes_a_disabled_boolean_toggle(self):
        bootstrap = build_bootstrap()
        controls = [
            field for section in bootstrap["sections"] for field in section["fields"]
            if field["path"] == "layout.number_figures"
        ]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["control"], "toggle")
        self.assertIs(bootstrap["config"]["layout"]["number_figures"], False)


class FigureNumberingRendererTests(unittest.TestCase):
    def make_report(self, *, enabled=False):
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
        config.layout.number_figures = enabled
        config.layout.image_placeholder_height_mm = 20
        config.layout.image_placeholder_border = False
        config.layout.show_page_numbers = False
        return ReportRenderer(config)

    def render_and_capture(self, report, blocks):
        """Capture text entering the real engine, after all caption processing."""
        calls = []
        original = report.engine.render_line

        def capture(text, *args, **kwargs):
            calls.append((text, len(report.pages)))
            return original(text, *args, **kwargs)

        with patch.object(report.engine, "render_line", side_effect=capture):
            report.render(blocks)
        return calls

    def test_disabled_numbering_preserves_original_markdown_and_html_captions(self):
        source = '![冷却曲线（实验）：温度，时间。](cooling.png)\n\n<img src="setup.png" alt="装置：测量；结果！">'
        report = self.make_report(enabled=False)
        calls = self.render_and_capture(report, parse_markdown(source))
        self.assertEqual([text for text, _ in calls], ["冷却曲线（实验）：温度，时间。", "装置：测量；结果！"])

    def test_enabled_numbering_uses_exact_fullwidth_colon_without_inserted_spaces(self):
        source = '![冷却曲线（实验）：温度，时间。](cooling.png)\n\n<img src="setup.png" alt="装置：测量；结果！">'
        report = self.make_report(enabled=True)
        calls = self.render_and_capture(report, parse_markdown(source))
        self.assertEqual([text for text, _ in calls], ["图1：冷却曲线（实验）：温度，时间。", "图2：装置：测量；结果！"])
        self.assertEqual(report.figure_counter, 2)

    def test_caption_fallback_keeps_alt_then_source_then_empty_placeholder(self):
        blocks = [
            ImageBlock(alt="原标题", src="ignored.png"),
            ImageBlock(alt="", src="figures/source.png"),
            ImageBlock(alt="", src=""),
        ]
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                report = self.make_report(enabled=enabled)
                calls = self.render_and_capture(report, blocks)
                titles = ["原标题", "figures/source.png", "插图空白"]
                expected = [f"图{index}：{title}" for index, title in enumerate(titles, 1)] if enabled else titles
                self.assertEqual([text for text, _ in calls], expected)

    def test_sequence_continues_across_headings_and_automatic_and_explicit_pages(self):
        report = self.make_report(enabled=True)
        # This budget forces automatic pagination before the second image.
        report.bottom_limit = report.margin_top + 125
        source = "![First](one.png)\n\n# Section\n\n![Second](two.png)\n<newpage>\n![Third](three.png)"
        calls = self.render_and_capture(report, parse_markdown(source))
        captions = [(text, page) for text, page in calls if text.startswith("图")]
        self.assertEqual([text for text, _ in captions], ["图1：First", "图2：Second", "图3：Third"])
        self.assertGreater(captions[1][1], captions[0][1])
        self.assertGreater(captions[2][1], captions[1][1])
        self.assertEqual(report.figure_counter, 3)

    def test_separate_renderer_starts_each_document_from_figure_one(self):
        first = self.make_report(enabled=True)
        self.assertEqual(first.figure_counter, 0)
        self.render_and_capture(first, parse_markdown("![A](a.png)\n\n![B](b.png)"))
        self.assertEqual(first.figure_counter, 2)
        second = self.make_report(enabled=True)
        self.assertEqual(second.figure_counter, 0)
        calls = self.render_and_capture(second, parse_markdown("![C](c.png)"))
        self.assertEqual([text for text, _ in calls], ["图1：C"])
        self.assertEqual(second.figure_counter, 1)

    def test_enabling_numbering_changes_only_the_caption_prefix(self):
        original_title = "图4：原文已有编号（保留）。"
        blocks = [ImageBlock(alt=original_title, src="example.png")]
        captions = []
        for enabled in (False, True):
            report = self.make_report(enabled=enabled)
            captions.append(self.render_and_capture(report, blocks)[0][0])
        self.assertEqual(captions, [original_title, "图1：" + original_title])
        self.assertEqual(blocks[0].alt, original_title)


if __name__ == "__main__":
    unittest.main()
