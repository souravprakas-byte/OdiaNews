from __future__ import annotations

import hashlib
import re
import string

try:
    from rapidfuzz.fuzz import token_set_ratio
except ModuleNotFoundError:  # pragma: no cover - local minimal runtime fallback.
    from difflib import SequenceMatcher

    def token_set_ratio(left: str, right: str) -> int:
        left_tokens = set(left.split())
        right_tokens = set(right.split())
        if left_tokens and left_tokens == right_tokens:
            return 100
        overlap = left_tokens & right_tokens
        if overlap:
            coverage = (2 * len(overlap)) / (len(left_tokens) + len(right_tokens))
            return max(int(coverage * 100), int(SequenceMatcher(None, left, right).ratio() * 100))
        return int(SequenceMatcher(None, left, right).ratio() * 100)


SOURCE_SUFFIX_RE = re.compile(
    r"\s+(?:-|--|\||:)\s+"
    r"(?:times of india|the indian express|indian express|oneindia|toi|odisha news|latest news)"
    r"\s*$",
    re.IGNORECASE,
)
PUNCTUATION_TABLE = str.maketrans("", "", string.punctuation)
WORD_RE = re.compile(r"[\w\u0b00-\u0b7f]+", re.UNICODE)


def normalize_text(text: str) -> str:
    text = text.casefold().translate(PUNCTUATION_TABLE)
    return " ".join(text.split())


def strip_source_suffix(title: str) -> str:
    return SOURCE_SUFFIX_RE.sub("", title).strip()


def title_key(title: str) -> str:
    return normalize_text(strip_source_suffix(title))


def content_hash(title: str, description: str) -> str:
    base = dedupe_base(title, description)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def dedupe_base(title: str, description: str) -> str:
    return f"{title} {description}"[:800]


def simple_simhash(text: str) -> str:
    vector = [0] * 64
    for word in WORD_RE.findall(normalize_text(text)):
        digest = int(hashlib.sha1(word.encode("utf-8")).hexdigest()[:16], 16)
        for bit in range(64):
            if digest & (1 << bit):
                vector[bit] += 1
            else:
                vector[bit] -= 1

    value = 0
    for bit, weight in enumerate(vector):
        if weight > 0:
            value |= 1 << bit
    return f"{value:016x}"


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def title_similarity(left: str, right: str) -> int:
    return int(token_set_ratio(left, right))
