import re

# Multi-word legal forms must be stripped as phrases before tokenisation.
_LEGAL_PHRASES = (
    "товариство з обмеженою відповідальністю",
    "приватне підприємство",
)
# Single-word tokens to drop (intentionally excludes "co" so "Build Co." → "build co").
_LEGAL_TOKENS = frozenset({
    "тов", "пп", "фоп", "дп", "ат", "пат", "прат",
    "llc", "ltd", "inc", "gmbh", "sa", "spa",
})
_NONWORD = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")

# Pre-compile phrase patterns (word-boundary-aware, case-insensitive already handled by lowercasing).
_PHRASE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in _LEGAL_PHRASES) + r")\b",
    flags=re.UNICODE,
)


def normalize_edrpou(value: str | None) -> str | None:
    """Canonical 8-digit EDRPOU, or None if no digits found."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    return digits.zfill(8) if len(digits) < 8 else digits


def normalize_company_name(value: str | None) -> str:
    """Lowercase, strip punctuation and leading/standalone legal forms."""
    if not value:
        return ""
    text = value.lower()
    # Strip multi-word legal phrases first.
    text = _PHRASE_RE.sub(" ", text)
    # Strip non-word characters (quotes, punctuation).
    text = _NONWORD.sub(" ", text)
    # Drop single-word legal form tokens.
    tokens = [t for t in _WS.split(text) if t and t not in _LEGAL_TOKENS]
    return " ".join(tokens).strip()


def cpv_division(cpv: str | None) -> str | None:
    """First two digits of a CPV code, or None."""
    if not cpv or len(cpv) < 2 or not cpv[:2].isdigit():
        return None
    return cpv[:2]
