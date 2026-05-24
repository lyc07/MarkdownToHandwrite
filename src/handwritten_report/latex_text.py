from __future__ import annotations

import re

GREEK_AND_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "theta": "θ",
    "lambda": "λ",
    "mu": "μ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "omega": "ω",
    "Delta": "Δ",
    "Omega": "Ω",
    "sum": "sum",
    "int": "int",
    "times": "×",
    "cdot": "·",
    "le": "<=",
    "ge": ">=",
    "neq": "!=",
    "approx": "~",
    "pm": "+/-",
    "infty": "inf",
    "to": "->",
    "rightarrow": "->",
    "leftarrow": "<-",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "ln": "ln",
    "log": "log",
    "exp": "exp",
}


def latex_to_hand_text(text: str) -> str:
    text = text.strip()
    text = text.removeprefix("$$").removesuffix("$$").strip()
    text = text.removeprefix(r"\[").removesuffix(r"\]").strip()
    text = re.sub(r"\\begin\{[^}]+\}|\\end\{[^}]+\}", "", text)
    text = text.replace(r"\\", "\n")
    text = text.replace(r"\%", "%")
    text = text.replace("&", " ")
    text = _replace_frac(text)
    text = _replace_sqrt(text)
    text = _replace_bar(text)
    text = _replace_simple_commands(text)
    text = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", text)
    text = re.sub(r"_\{([^{}]+)\}", r"_(\1)", text)
    text = re.sub(r"\\[lr](?:eft|ight)?", "", text)
    text = text.replace("{", "(").replace("}", ")")
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _replace_simple_commands(text: str) -> str:
    for name, value in sorted(GREEK_AND_SYMBOLS.items(), key=lambda item: -len(item[0])):
        text = text.replace("\\" + name, value)
    return text


def _replace_frac(text: str) -> str:
    pattern = re.compile(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(lambda m: f"({m.group(1)})/({m.group(2)})", text)
    return text


def _replace_sqrt(text: str) -> str:
    pattern = re.compile(r"\\sqrt\s*\{([^{}]+)\}")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(lambda m: f"√({m.group(1)})", text)
    return text


def _replace_bar(text: str) -> str:
    pattern = re.compile(r"\\(?:bar|overline)\s*\{([^{}]+)\}")
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(lambda m: f"avg({m.group(1)})", text)
    return text
