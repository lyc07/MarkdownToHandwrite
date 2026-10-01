"""Check the rendered radical's visible joins, independently of text glyphs."""

import unittest
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np
from PIL import Image

from markdown_to_handwrite.config import HandwritingConfig
from markdown_to_handwrite.handwriting import HandwritingEngine
from markdown_to_handwrite.math_renderer import (
    FormulaRenderer,
    FractionNode,
    MathBox,
    RootNode,
    SpaceNode,
)


def visible_components(image):
    """Ignore faint antialias halos and count 8-connected visible ink regions."""
    remaining = set(map(tuple, np.argwhere(np.asarray(image.getchannel("A")) >= 64)))
    components = []
    while remaining:
        pending = [remaining.pop()]
        points = []
        while pending:
            y, x = pending.pop()
            points.append((int(x), int(y)))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    neighbor = (y + dy, x + dx)
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        pending.append(neighbor)
        # A few isolated resampling pixels do not constitute a broken stroke.
        if len(points) > 3:
            components.append(points)
    return sorted(components, key=len, reverse=True)


@contextmanager
def isolated_radicals(renderer):
    """Keep real glyph/fraction dimensions and random draws; hide their ink."""
    original_text = renderer._text_box
    original_fraction = renderer._fraction_box

    def transparent(box):
        return MathBox(Image.new("RGBA", box.image.size), box.baseline)

    def text(*args, **kwargs):
        return transparent(original_text(*args, **kwargs))

    def fraction(*args, **kwargs):
        return transparent(original_fraction(*args, **kwargs))

    with (
        patch.object(renderer, "_text_box", side_effect=text),
        patch.object(renderer, "_fraction_box", side_effect=fraction),
    ):
        yield


class RootContinuityTests(unittest.TestCase):
    def make_renderer(self, *, sdt, seed, reference=40, pen_width=16):
        config = HandwritingConfig(
            prefer_handright=False,
            sdt_trajectory_enabled=sdt,
            sdt_stroke_width=pen_width,
            second_layer_enabled=True,
        )
        engine = HandwritingEngine(config, reference_size_px=reference)
        self.assertEqual(engine.uses_sdt_trajectories, sdt)
        return FormulaRenderer(engine, seed=seed)

    def assert_joined_roots(self, image, *, count=1, minimum_height=8):
        components = visible_components(image)
        self.assertEqual(
            len(components), count,
            f"Expected {count} continuous radical(s); visible component sizes: "
            f"{[len(component) for component in components]}",
        )
        # A missing hook would leave a connected bar, but would not be a root.
        for component in components:
            self.assertGreaterEqual(max(y for _, y in component) - min(y for _, y in component), minimum_height)

    def test_tall_nested_fraction_root_connects_hook_to_overbar(self):
        renderer = self.make_renderer(sdt=True, seed=2, reference=40, pen_width=10)
        node = RootNode(FractionNode(
            FractionNode(SpaceNode(2), SpaceNode(1)),
            FractionNode(SpaceNode(1), SpaceNode(1)),
        ))
        with isolated_radicals(renderer):
            box = renderer._layout_with_weight_group(node, 72, "probe:display:0", True)
        # Before the curve fix, this unscaled radical split into a 410-pixel
        # hook and a 263-pixel overbar, with no alpha >= 64 connection at x=56.
        self.assert_joined_roots(box.image, minimum_height=100)

    def test_thin_tall_root_keeps_a_visible_join(self):
        renderer = self.make_renderer(sdt=True, seed=0, reference=17, pen_width=6)
        node = RootNode(FractionNode(
            FractionNode(SpaceNode(2), SpaceNode(1)),
            FractionNode(SpaceNode(1), SpaceNode(1)),
        ))
        with isolated_radicals(renderer):
            box = renderer._layout_with_weight_group(node, 40, "probe:display:0", True)
        self.assert_joined_roots(box.image, minimum_height=60)

    def test_reported_inertia_formula_has_a_continuous_root(self):
        latex = r"T=2\pi\sqrt{\frac{I}{mgh}}\tag{5}"
        cases = (
            (True, 72, 1, 25, 10),
            (False, 34, 7, 34, 16),
            (False, 67, 17, 67, 16),
            (True, 34, 7, 34, 16),
            (True, 67, 17, 67, 16),
        )
        for sdt, size, seed, reference, pen_width in cases:
            with self.subTest(sdt=sdt, size=size, seed=seed):
                renderer = self.make_renderer(sdt=sdt, seed=seed, reference=reference, pen_width=pen_width)
                with isolated_radicals(renderer):
                    image = renderer.render(latex, size, 2000, seed_extra="probe")
                self.assert_joined_roots(image, minimum_height=size // 2)

    def test_plain_and_indexed_inline_roots_connect_at_different_sizes(self):
        for latex in (r"\sqrt{x}", r"\sqrt[3]{x+1}"):
            for sdt, size, seed in ((False, 16, 7), (True, 48, 42)):
                with self.subTest(latex=latex, sdt=sdt, size=size, seed=seed):
                    renderer = self.make_renderer(sdt=sdt, seed=seed)
                    with isolated_radicals(renderer):
                        box = renderer.render_inline(latex, size, 1200, seed_extra="inline-root")
                    self.assert_joined_roots(box.image, minimum_height=size // 2)

    def test_nested_radicals_each_retain_their_own_continuous_stroke(self):
        for latex in (r"\sqrt{1+\sqrt{x}}", r"\sqrt{\sqrt{\frac{x}{y}}}"):
            for sdt, size, seed in ((False, 55, 7), (True, 67, 2)):
                with self.subTest(latex=latex, sdt=sdt, size=size, seed=seed):
                    renderer = self.make_renderer(sdt=sdt, seed=seed)
                    with isolated_radicals(renderer):
                        box = renderer.render_inline(latex, size, 1200, seed_extra="nested-root")
                    self.assert_joined_roots(box.image, count=2, minimum_height=size // 2)


if __name__ == "__main__":
    unittest.main()
