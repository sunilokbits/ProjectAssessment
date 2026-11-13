"""Light-weight text utilities used for keyword matching and semantic de-duplication.

Deterministic and dependency-free so the engine works offline; embeddings can be
plugged in later behind ``similarity``.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

STOPWORDS = frozenset(
    """a an the is are was were be been being do does did have has had of in on at to for from by with
    and or not no yes your you our we they it its this that these those there their which who whom what
    when where why how any all each every some such will would can could should shall may might must
    please describe explain provide list identify confirm whether if as into about than then so also
    existing current currently client organisation organization project""".split()
)

_WORD = re.compile(r"[a-z0-9][a-z0-9\-/+.]*")


def normalise(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _stem(w: str) -> str:
    for suf in ("ing", "ies", "es", "s", "ed"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str, synonyms: dict[str, str] | None = None) -> frozenset[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        w = w.strip(".-/")
        if not w or w in STOPWORDS:
            continue
        w = _stem(w)
        if synonyms:
            w = synonyms.get(w, w)
        out.append(w)
    return frozenset(out)


def token_similarity(ta: frozenset[str], tb: frozenset[str], threshold: float = 0.0) -> float:
    """Similarity of two pre-tokenised texts. Below ``threshold`` the exact value is not needed,
    so cheap upper bounds short-circuit the expensive sequence match."""
    if not ta or not tb:
        return 0.0
    jacc = len(ta & tb) / len(ta | tb)
    if jacc >= threshold > 0:
        return jacc
    sm = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb)), autojunk=False)
    need = threshold / 0.95
    if threshold and (sm.real_quick_ratio() < need or sm.quick_ratio() < need):
        return jacc
    return max(jacc, sm.ratio() * 0.95)


def similarity(a: str, b: str, synonyms: dict[str, str] | None = None) -> float:
    return token_similarity(tokens(a, synonyms), tokens(b, synonyms))


@lru_cache(maxsize=4096)
def _kw_re(keyword: str) -> re.Pattern[str]:
    kw = re.escape(keyword.lower()).replace(r"\ ", r"[\s\-_]+")
    plural = "(?:s|es)?" if keyword[-1:].isalpha() else ""  # 'customer' also matches 'customers'
    return re.compile(rf"(?<![a-z0-9]){kw}{plural}(?![a-z0-9])")


def count_keyword(text_lower: str, keyword: str) -> int:
    if keyword is None or keyword == "":
        return 0
    return len(_kw_re(str(keyword)).findall(text_lower))


def contains_keyword(text_lower: str, keyword: str) -> bool:
    # keywords may arrive as numbers from YAML (e.g. 360, 5G is fine but 360 is an int)
    return keyword is not None and keyword != "" and _kw_re(str(keyword)).search(text_lower) is not None


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\r", "", text)
    parts = re.split(r"(?<=[.!?])\s+|\n\s*[-*••]\s*|\n{2,}|\n(?=\s*\d+[.)]\s)", text)
    out = []
    for p in parts:
        p = re.sub(r"^\s*(\d+[.)]|[-*••])\s*", "", p).strip()
        p = re.sub(r"\s+", " ", p)
        if len(p) >= 12:
            out.append(p)
    return out
