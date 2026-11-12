"""Text normalisation shared by quote checks, vendor matching, duplicate checks and PO matching."""
import re
import unicodedata

_DASH_CHARACTERS = "‐‑‒–—−"
_SPACE_CHARACTERS = "   "
_DASH_TRANSLATION = str.maketrans(_DASH_CHARACTERS + _SPACE_CHARACTERS, "-" * len(_DASH_CHARACTERS) + " " * len(_SPACE_CHARACTERS))


def normalize_for_search(text: str) -> str:
    """Case-folded, with ligatures split (NFKC: 'ﬁ' -> 'fi'), typographic dashes and spaces made plain, and all
    whitespace collapsed to one space. PDF text extraction produces all of these."""
    return " ".join(unicodedata.normalize("NFKC", text).translate(_DASH_TRANSLATION).casefold().split())


def keep_alphanumeric(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def keep_digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def normalize_words(text: str) -> str:
    """Case-folded words with punctuation removed, for fuzzy comparison of names and descriptions."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.casefold()).split())
