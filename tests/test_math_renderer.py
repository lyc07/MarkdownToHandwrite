import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from PIL import Image, ImageChops

from markdown_to_handwrite.config import HandwritingConfig, ReportConfig, load_config
from markdown_to_handwrite.handwriting import HandwritingEngine
from markdown_to_handwrite.math_renderer import (
    FormulaRenderer,
    GeneratedSymbolNode,
    LatexMathParser,
    LatexRenderError,
    RowNode,
    ScriptNode,
)
from markdown_to_handwrite.markdown_parser import FormulaBlock, parse_markdown
from markdown_to_handwrite.renderer import ReportRenderer


class FormulaRendererTests(unittest.TestCase):
    def test_sdt_formula_rules_use_the_same_pen_width_at_every_math_size(self):
        engine = HandwritingEngine(
            HandwritingConfig(prefer_handright=False, sdt_stroke_width=14),
            reference_size_px=34,
            math_reference_size_px=55,
        )
        renderer = FormulaRenderer(engine, seed=7)

        self.assertEqual(renderer._stroke_width(18), engine.uniform_pen_width_px())
        self.assertEqual(renderer._stroke_width(72), engine.uniform_pen_width_px())

    def test_ink_density_parameter_also_affects_generated_rules(self):
        plain_engine = HandwritingEngine(
            HandwritingConfig(
                ink_density_jitter=0.0,
                dry_brush_probability=0.0,
                math_rule_tilt_ratio=0.0,
                math_rule_wobble_ratio=0.0,
                math_rule_jitter_ratio=0.0,
            ),
            reference_size_px=40,
        )
        varied_engine = HandwritingEngine(
            HandwritingConfig(
                ink_density_jitter=0.4,
                dry_brush_probability=0.0,
                math_rule_tilt_ratio=0.0,
                math_rule_wobble_ratio=0.0,
                math_rule_jitter_ratio=0.0,
            ),
            reference_size_px=40,
        )
        plain = Image.new("RGBA", (180, 30), (0, 0, 0, 0))
        varied = Image.new("RGBA", (180, 30), (0, 0, 0, 0))
        FormulaRenderer(plain_engine, seed=17).draw_horizontal_rule(plain, 8, 15, 172, 40)
        FormulaRenderer(varied_engine, seed=17).draw_horizontal_rule(varied, 8, 15, 172, 40)

        plain_bbox = plain.getchannel("A").getbbox()
        varied_bbox = varied.getchannel("A").getbbox()
        self.assertIsNotNone(plain_bbox)
        self.assertIsNotNone(varied_bbox)
        self.assertTrue(all(abs(left - right) <= 1 for left, right in zip(plain_bbox, varied_bbox)))
        self.assertLess(sum(varied.getchannel("A").getdata()), sum(plain.getchannel("A").getdata()))

    @classmethod
    def setUpClass(cls):
        engine = HandwritingEngine(load_config("examples/config.json").handwriting)
        cls.renderer = FormulaRenderer(engine, seed=42)

    def test_fraction_creates_vertical_layout(self):
        plain = self.renderer.render("g = 4", 34, 900)
        fraction = self.renderer.render(r"g = \frac{4\pi^2 l}{T^2}", 34, 900)
        self.assertGreater(fraction.height, plain.height)
        self.assertIsNotNone(fraction.getchannel("A").getbbox())

    def test_root_and_accent_render(self):
        image = self.renderer.render(r"\bar{g}+\overline{v}+\underline{x} = 2\pi\sqrt{\frac{l}{g}}", 34, 1200)
        self.assertGreater(image.width, 0)
        self.assertGreater(image.height, 34)

    def test_math_rule_motion_can_be_disabled_by_config(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                math_rule_tilt_ratio=0.0,
                math_rule_wobble_ratio=0.0,
                math_rule_jitter_ratio=0.0,
            )
        )
        renderer = FormulaRenderer(engine, seed=7)
        self.assertEqual(renderer._rule_variation(72), (0.0, 0.0, 0.0))
        image = renderer.render(r"\frac{a+b}{c+d}+\sqrt{x}", 42, 900)
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_math_rule_jitter_count_grows_logarithmically(self):
        self.assertEqual(self.renderer._rule_jitter_count(80, 40), 1)
        self.assertEqual(self.renderer._rule_jitter_count(1280, 40), 5)

    def test_math_rule_jitter_offsets_are_small_but_visible(self):
        offsets = [abs(self.renderer._rule_jitter_offset(1.0)) for _ in range(12)]
        self.assertTrue(all(0.35 <= offset <= 1.0 for offset in offsets))

    def test_rule_curve_supports_vertical_lines_and_preserves_endpoints(self):
        points = self.renderer._rule_curve(12, 8, 12, 128, 1.5, 0.0, 40)
        self.assertEqual(points[0], (12.0, 8.0))
        self.assertAlmostEqual(points[-1][0], 12.0)
        self.assertAlmostEqual(points[-1][1], 128.0)
        self.assertTrue(any(abs(x - 12) > 0.5 for x, _ in points[1:-1]))

    def test_inline_formula_exposes_math_baseline(self):
        box = self.renderer.render_inline(r"T=2\pi\sqrt{l/g}", 32, 600)
        self.assertGreater(box.baseline, 0)
        self.assertGreater(box.height, 32)

    def test_ascii_apostrophes_become_generated_prime_superscripts(self):
        parsed = LatexMathParser("f''(x)").parse()

        self.assertIsInstance(parsed, RowNode)
        self.assertIsInstance(parsed.items[0], ScriptNode)
        self.assertIsInstance(parsed.items[0].superscript, GeneratedSymbolNode)
        self.assertEqual(parsed.items[0].superscript.kind, "prime")
        self.assertEqual(parsed.items[0].superscript.count, 2)

        image = self.renderer.render(r"f'(x)+g''(x)+f^\prime(x)", 48, 1000)
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_cdot_is_generated_on_the_math_axis(self):
        size = 55
        box = self.renderer._generated_symbol_box(GeneratedSymbolNode("cdot"), size, "cdot-test")
        bbox = box.image.getchannel("A").getbbox()

        self.assertIsNotNone(bbox)
        dot_center = (bbox[1] + bbox[3]) / 2
        distance_above_baseline = box.baseline - dot_center
        self.assertGreater(distance_above_baseline, size * 0.18)
        self.assertLess(distance_above_baseline, size * 0.34)

        rendered = self.renderer.render(r"a\cdot b+c\cdot d", size, 1000)
        self.assertIsNotNone(rendered.getchannel("A").getbbox())

    def test_common_inline_latex_wrappers_relations_and_modulo_render(self):
        box = self.renderer.render_inline(
            r"\mathbb{R}\ni x\iff x\notin A,\quad f:x\mapsto y,\quad "
            r"a\oplus b\equiv c\pmod n,\quad \therefore\overrightarrow{AB}\parallel l",
            34,
            1600,
        )

        self.assertGreater(box.width, 200)
        self.assertIsNotNone(box.image.getchannel("A").getbbox())

    def test_formula_components_share_one_weight_perturbation_group(self):
        engine = HandwritingEngine(HandwritingConfig(prefer_handright=False))
        renderer = FormulaRenderer(engine, seed=19)
        groups: list[str | None] = []
        rule_groups: list[str] = []
        original = engine.render_line
        original_rule_adjustment = engine.grouped_stroke_weight_adjustment

        def capture(*args, **kwargs):
            groups.append(kwargs.get("weight_seed_extra"))
            return original(*args, **kwargs)

        def capture_rule(group, math_mode=False):
            rule_groups.append(group)
            return original_rule_adjustment(group, math_mode=math_mode)

        engine.render_line = capture
        engine.grouped_stroke_weight_adjustment = capture_rule
        renderer.render(r"E=\frac{x_1+x_2}{\sqrt{a+b}}", 38, 1000, seed_extra="shared")

        self.assertGreater(len(groups), 3)
        self.assertEqual(len(set(groups)), 1)
        self.assertEqual(groups[0], "shared:display:0")
        self.assertGreater(len(rule_groups), 1)
        self.assertEqual(set(rule_groups), {"shared:display:0"})

    def test_unsupported_command_raises_instead_of_becoming_text(self):
        with self.assertRaises(LatexRenderError):
            self.renderer.render(r"y = \unsupported{x}", 34, 900)

    def test_scripts_stay_near_the_base_line(self):
        base = self.renderer.render_inline("U", 42, 600)
        scripted = self.renderer.render_inline(r"U_{H}^{2}", 42, 600)
        self.assertLess(scripted.height, base.height + 42)

    def test_formula_main_text_and_scripts_use_their_own_relative_vertical_sigma(self):
        engine = HandwritingEngine(
            HandwritingConfig(
                prefer_handright=False,
                perturb_y_sigma_px=8.0,
                math_perturb_y_sigma_ratio=0.02,
            )
        )
        renderer = FormulaRenderer(engine, seed=7)
        calls: list[tuple[int, bool, float]] = []
        original = engine._vertical_position_sigma

        def capture(size_px, math_mode=False):
            sigma = original(size_px, math_mode=math_mode)
            calls.append((size_px, math_mode, sigma))
            return sigma

        engine._vertical_position_sigma = capture
        renderer.render_inline(r"x_i^2+f'+a\cdot b", 42, 600)

        self.assertTrue(calls)
        self.assertTrue(all(math_mode for _, math_mode, _ in calls))
        self.assertGreater(max(size for size, _, _ in calls), min(size for size, _, _ in calls))
        self.assertTrue(all(abs(sigma - size * 0.02) < 1e-9 for size, _, sigma in calls))

    def test_large_operator_limits_follow_latex_display_rules(self):
        size = 48
        sum_inline = self.renderer.render_inline(r"\sum_{i=0}^{n}", size, 600)
        sum_inline_limits = self.renderer.render_inline(r"\sum\limits_{i=0}^{n}", size, 600)
        sum_display = self.renderer.render(r"\sum_{i=0}^{n}", size, 600)
        sum_display_nolimits = self.renderer.render(r"\sum\nolimits_{i=0}^{n}", size, 600)
        integral_display = self.renderer.render(r"\int_{0}^{\infty}", size, 600)
        integral_limits = self.renderer.render(r"\int\limits_{0}^{\infty}", size, 600)
        lim_inline = self.renderer.render_inline(r"\lim_{x\to0} f(x)", size, 800)
        lim_display = self.renderer.render(r"\lim_{x\to0} f(x)", size, 800)
        self.assertGreater(sum_inline_limits.height, sum_inline.height)
        self.assertGreater(sum_display.height, sum_display_nolimits.height)
        self.assertGreater(integral_limits.height, integral_display.height)
        self.assertGreater(lim_display.height, lim_inline.height)

    def test_integral_side_limits_and_rooted_fraction_render(self):
        image = self.renderer.render(
            r"\int_{0}^{\sqrt{\frac{l}{g}}} \frac{dx}{\sqrt{\frac{a+b}{c+d}}}",
            52,
            1300,
        )
        self.assertGreater(image.height, 52)
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_latex_style_commands_override_operator_limit_placement(self):
        size = 48
        inline_sum = self.renderer.render_inline(r"\sum_{i=0}^{n}", size, 600)
        inline_display_sum = self.renderer.render_inline(r"\displaystyle\sum_{i=0}^{n}", size, 600)
        display_sum = self.renderer.render(r"\sum_{i=0}^{n}", size, 600)
        display_text_sum = self.renderer.render(r"\textstyle\sum_{i=0}^{n}", size, 600)
        self.assertGreater(inline_display_sum.height, inline_sum.height)
        self.assertGreater(display_sum.height, display_text_sum.height)

    def test_report_renderer_leaves_invalid_formula_blank_and_logs_source(self):
        config = ReportConfig()
        config.background.auto_discover = False
        report = ReportRenderer(config)
        output = StringIO()
        with redirect_stderr(output):
            image = report._render_formula_image(r"y=\unsupported{x}", "test")
        self.assertIsNone(image.getchannel("A").getbbox())
        self.assertIn(r"y=\unsupported{x}", output.getvalue())

    def test_common_calculus_and_set_commands_render(self):
        image = self.renderer.render(
            r"I=\iint_{D_1} f\,du\,dv,\quad D=\{x\mid x\ge0\}\setminus\emptyset,\quad 45^\circ,\quad x\to\infin",
            34,
            1900,
        )
        self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_indexed_root_accents_and_binomial_render(self):
        image = self.renderer.render(
            r"x=\sqrt[3]{a}+\hat{v}+\dot{x}+\binom{n}{k}",
            38,
            1400,
        )
        self.assertGreater(image.height, 38)

    def test_matrix_and_cases_render_as_two_dimensional_structures(self):
        matrix = self.renderer.render(r"A=\begin{bmatrix}a&b\\c&d\end{bmatrix}", 36, 1200)
        cases = self.renderer.render(r"f(x)=\begin{cases}x,&x\ge0\\-x,&x<0\end{cases}", 36, 1200)
        self.assertGreater(matrix.height, 36)
        self.assertGreater(cases.height, 36)

    def test_extended_example_math_is_supported(self):
        source = Path("examples/test.md").read_text(encoding="utf-8")
        blocks = parse_markdown(source)
        formulas: list[str] = []
        for block in blocks:
            if isinstance(block, FormulaBlock):
                formulas.append(block.text)
            formulas.extend(
                part.text
                for part in getattr(block, "parts", [])
                if getattr(part, "kind", None) == "math"
            )
        self.assertGreater(len(formulas), 20)
        for formula in formulas:
            with self.subTest(formula=formula):
                self.renderer.render_inline(formula, 32, 1600)


class ReportRuleRenderingTests(unittest.TestCase):
    def test_heading_table_and_list_use_two_dimensional_inline_math(self):
        config = ReportConfig()
        config.background.auto_discover = False
        config.background.style = "plain"
        config.handwriting.prefer_handright = False
        config.layout.show_page_numbers = False
        report = ReportRenderer(config)
        formulas: list[str] = []
        original_render_inline = report.formula_renderer.render_inline

        def capture(latex, *args, **kwargs):
            formulas.append(latex)
            return original_render_inline(latex, *args, **kwargs)

        report.formula_renderer.render_inline = capture
        pages = report.render(
            parse_markdown(
                r"""# Energy \(E=mc^2\)

| Quantity | Value |
| --- | --- |
| Speed | $v=\frac{s}{t}$ |

1. Period \(T=2\pi\sqrt{l/g}\)
"""
            )
        )

        self.assertEqual(formulas, ["E=mc^2", r"v=\frac{s}{t}", r"T=2\pi\sqrt{l/g}"])
        self.assertIsNotNone(pages[0].getchannel("A").getbbox())

    def test_generated_paper_style_overrides_auto_discovered_background(self):
        generated_config = ReportConfig()
        generated_config.background.style = "grid"
        generated_config.background.auto_discover = True
        generated = ReportRenderer(generated_config)
        self.assertIsNone(generated.background_path)

        image_config = ReportConfig()
        image_config.background.style = "image"
        image_config.background.auto_discover = True
        image_backed = ReportRenderer(image_config)
        self.assertIsNotNone(image_backed.background_path)
        self.assertTrue(image_backed.background_path.is_file())

    def test_paragraph_uses_remaining_space_before_following_formula(self):
        config = ReportConfig()
        config.background.auto_discover = False
        config.background.style = "plain"
        config.background.draw_margin_line = False
        config.handwriting.prefer_handright = False
        config.layout.show_page_numbers = False
        report = ReportRenderer(config)
        body_size = round(config.handwriting.body_font_pt / 72 * config.page.dpi)
        line_height = round(body_size * config.handwriting.line_spacing)
        paragraph_gap = round(config.layout.paragraph_gap_mm / 25.4 * config.page.dpi)
        formula_height = report._formula_height(
            report._render_formula_image(r"y=\frac{1}{2}", "remaining-space-test")
        )
        report.y = report.bottom_limit - (line_height + paragraph_gap + max(1, formula_height // 2))
        first_page_before = report.pages[0].convert("RGB").copy()
        pages = report.render(parse_markdown("页底仍可写的正文\n\n$$\ny=\\frac{1}{2}\n$$\n"))
        difference = ImageChops.difference(pages[0].convert("RGB"), first_page_before)
        self.assertEqual(len(pages), 2)
        self.assertIsNotNone(difference.getbbox())

    def test_paragraph_justification_only_targets_full_non_final_lines(self):
        config = ReportConfig()
        config.background.auto_discover = False
        config.handwriting.prefer_handright = False
        report = ReportRenderer(config)
        size = 34
        line = "正文内容正文内容正文内容"
        width = round(report.engine.measure(line, size) * 1.08)
        self.assertTrue(report._should_justify_paragraph_line(line, 0, 2, size, width))
        self.assertFalse(report._should_justify_paragraph_line(line, 1, 2, size, width))
        self.assertFalse(report._should_justify_paragraph_line("短行", 0, 2, size, width))

    def test_table_horizontal_borders_use_formula_rule_style(self):
        config = ReportConfig()
        config.background.auto_discover = False
        config.handwriting.prefer_handright = False
        report = ReportRenderer(config)
        calls: list[tuple] = []
        original = report.formula_renderer.draw_horizontal_rule

        def capture(*args, **kwargs):
            calls.append(args)
            return original(*args, **kwargs)

        report.formula_renderer.draw_horizontal_rule = capture
        report.render(parse_markdown("| A | B |\n| - | - |\n| 1 | 2 |\n"))
        self.assertEqual(len(calls), 3)

    def test_table_vertical_borders_use_formula_rule_style(self):
        config = ReportConfig()
        config.background.auto_discover = False
        config.handwriting.prefer_handright = False
        report = ReportRenderer(config)
        calls: list[tuple[tuple, dict]] = []
        original = report.formula_renderer.draw_rule

        def capture(*args, **kwargs):
            calls.append((args, kwargs))
            return original(*args, **kwargs)

        report.formula_renderer.draw_rule = capture
        report.render(parse_markdown("| A | B |\n| - | - |\n| 1 | 2 |\n"))
        vertical = [
            (args, kwargs)
            for args, kwargs in calls
            if args[1] == args[3] and args[2] != args[4]
        ]
        self.assertEqual(len(vertical), 6)
        self.assertTrue(all(kwargs["anchor_ends"] for _, kwargs in vertical))

    def test_page_numbers_can_be_disabled_in_layout_config(self):
        enabled_config = ReportConfig()
        enabled_config.background.auto_discover = False
        enabled_config.layout.show_page_numbers = True
        disabled_config = ReportConfig()
        disabled_config.background.auto_discover = False
        disabled_config.layout.show_page_numbers = False
        enabled = ReportRenderer(enabled_config)
        disabled = ReportRenderer(disabled_config)
        footer_calls: list[bool] = []
        disabled._draw_footers = lambda: footer_calls.append(True)
        disabled.render(parse_markdown("正文"))
        self.assertEqual(footer_calls, [])
        self.assertGreater(disabled.bottom_limit, enabled.bottom_limit)


if __name__ == "__main__":
    unittest.main()
