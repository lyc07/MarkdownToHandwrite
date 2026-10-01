from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config, validate_layout_options
from .markdown_parser import parse_markdown
from .renderer import ReportRenderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a handwritten lab-report PDF from Markdown.")
    parser.add_argument("input", help="Input Markdown file.")
    parser.add_argument("-o", "--output", default="output/pdf/report.pdf", help="Output PDF path.")
    parser.add_argument("-c", "--config", help="Optional JSON config file.")
    parser.add_argument("--background", choices=["plain", "lined", "grid", "dot", "image"], help="Override background style.")
    parser.add_argument("--background-image", help="Use an image as page background.")
    parser.add_argument("--font", help="Override handwriting font path.")
    parser.add_argument("--paper-color", help="Override paper color, e.g. #fffdf4.")
    parser.add_argument("--ink-color", help="Override ink color, e.g. #17233b.")
    parser.add_argument("--seed", help="Override random seed.")
    parser.add_argument("--dpi", type=int, help="Override render DPI.")
    parser.add_argument("--char-spacing", type=float, help="Character advance adjustment in output pixels (-12 to 24).")
    parser.add_argument("--spacing-jitter", type=float, help="Character advance jitter sigma as a font-size ratio (0 to 0.1; 0 disables it).")
    justification = parser.add_mutually_exclusive_group()
    justification.add_argument("--justify", dest="justify", action="store_true", help="Stretch eligible wrapped paragraph lines toward the right margin (up to 18%%).")
    justification.add_argument("--no-justify", dest="justify", action="store_false", help="Disable paragraph line stretching.")
    parser.set_defaults(justify=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    config = load_config(args.config)
    if args.background:
        config.background.style = args.background
        if not args.background_image:
            config.background.image = None
            config.background.auto_discover = False
    if args.background_image:
        config.background.image = args.background_image
        config.background.auto_discover = False
    if args.font:
        config.handwriting.font_path = args.font
    if args.paper_color:
        config.background.paper_color = args.paper_color
    if args.ink_color:
        config.handwriting.ink_color = args.ink_color
    if args.seed is not None:
        config.handwriting.seed = args.seed
    if args.dpi:
        config.page.dpi = args.dpi
    if args.char_spacing is not None:
        config.handwriting.word_spacing_px = args.char_spacing
    if args.spacing_jitter is not None:
        config.handwriting.advance_jitter_sigma_ratio = args.spacing_jitter
    if args.justify is not None:
        config.layout.justify_paragraphs = args.justify
    try:
        validate_layout_options(config)
    except ValueError as error:
        parser.error(str(error))

    source = input_path.read_text(encoding="utf-8")
    blocks = parse_markdown(source)
    renderer = ReportRenderer(config, base_dir=input_path.parent)
    pages = renderer.render(blocks)
    output = renderer.save_pdf(args.output)
    engine = (
        "sdt-trajectories"
        if renderer.engine.uses_sdt_trajectories
        else "handright"
        if renderer.engine.handright_available
        else "pillow-fallback"
    )
    font_chain = " -> ".join(renderer.engine.font_paths)
    print(
        f"Generated {output} ({len(pages)} page(s), engine={engine}, "
        f"fonts={font_chain})"
    )
    return 0
