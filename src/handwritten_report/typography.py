from __future__ import annotations


_PUNCTUATION_REPLACEMENTS = {
    "，": ",",
    "。": ".",
    "、": ",",
    "；": ";",
    "：": ":",
    "！": "!",
    "？": "?",
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "〔": "[",
    "〕": "]",
    "《": "<",
    "》": ">",
    "〈": "<",
    "〉": ">",
    "“": '"',
    "”": '"',
    "„": '"',
    "‘": "'",
    "’": "'",
    "「": '"',
    "」": '"',
    "『": '"',
    "』": '"',
    "—": "--",
    "…": "...",
    "　": " ",
}
for fullwidth, ascii_char in zip(
    "！＂＃＄％＆＇（）＊＋，－．／：；＜＝＞？＠［＼］＾＿｀｛｜｝～",
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~",
):
    _PUNCTUATION_REPLACEMENTS[fullwidth] = ascii_char

_PUNCTUATION_TABLE = str.maketrans(_PUNCTUATION_REPLACEMENTS)


def westernize_punctuation(text: str) -> str:
    """Convert Chinese and full-width punctuation into ASCII punctuation."""
    text = text.replace("……", "...").replace("——", "--")
    return text.translate(_PUNCTUATION_TABLE)
