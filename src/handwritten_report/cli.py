from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .markdown_parser import parse_markdown
from .renderer import ReportRenderer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a handwritten lab-report PDF from Markdown.")
    parser.add_argument("input", help="Input Markdown file.")
    parser.add_argument("-o", "--output", default="output/pdf/report.pdf", help="Output PDF path.")
    parser.add_argument("-c", "--config", help="Optional JSON config file.")
    parser.add_argument("--background", choices=["plain", "lined", "grid", "dot"], help="Override background style.")
    parser.add_argument("--background-image", help="Use an image as page background.")
    parser.add_argument("--font", help="Override handwriting font path.")
    parser.add_argument("--paper-color", help="Override paper color, e.g. #fffdf4.")
    parser.add_argument("--ink-color", help="Override ink color, e.g. #17233b.")
    parser.add_argument("--seed", help="Override random seed.")
    parser.add_argument("--dpi", type=int, help="Override render DPI.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

    source = input_path.read_text(encoding="utf-8")
    blocks = parse_markdown(source)
    renderer = ReportRenderer(config, base_dir=input_path.parent)
    pages = renderer.render(blocks)
    output = renderer.save_pdf(args.output)
    engine = "handright" if renderer.engine.handright_available else "pillow-fallback"
    font_chain = " -> ".join(renderer.engine.font_paths)
    print(
        f"Generated {output} ({len(pages)} page(s), engine={engine}, "
        f"fonts={font_chain})"
    )
    return 0
