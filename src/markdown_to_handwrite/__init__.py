"""Markdown to handwritten PDF report generator."""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.1.0"


def _bootstrap_local_deps() -> None:
    root = Path(__file__).resolve().parents[2]
    deps = root / ".codex_deps"
    if deps.exists():
        deps_str = str(deps)
        if deps_str not in sys.path:
            sys.path.insert(0, deps_str)


_bootstrap_local_deps()

