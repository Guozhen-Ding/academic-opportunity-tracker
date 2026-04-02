from __future__ import annotations

import re
from collections import Counter


STOPWORDS = {
    "a", "about", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "into", "is", "of", "on", "or", "that", "the", "to", "with", "using",
    "their", "this", "these", "those", "my", "our", "your", "you", "we", "i",
    "within", "across", "through", "over", "under", "role", "position", "post",
    "candidate", "research", "researcher", "university", "department",
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify_query(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def sentence_chunks(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", normalize_whitespace(text))
    return [part for part in parts if part]


def extract_keywords(text: str, top_n: int = 30) -> list[str]:
    normalized = normalize_whitespace(text).lower()
    words = re.findall(r"[a-z][a-z0-9+\-]{2,}", normalized)
    filtered = [word for word in words if word not in STOPWORDS]
    counts = Counter(filtered)
    multiword = re.findall(r"\b[a-z][a-z0-9+\-]{2,}\s+[a-z][a-z0-9+\-]{2,}\b", normalized)
    for phrase in multiword:
        if not any(token in STOPWORDS for token in phrase.split()):
            counts[phrase] += 2
    return [term for term, _ in counts.most_common(top_n)]


def find_section(text: str, headings: list[str]) -> str:
    normalized = text.replace("\r", "\n")
    pattern = r"(?ims)^({})\s*$".format("|".join(re.escape(item) for item in headings))
    matches = list(re.finditer(pattern, normalized))
    if not matches:
        return ""
    start = matches[0].end()
    remainder = normalized[start:]
    next_heading = re.search(r"(?im)^[A-Z][A-Z &/\-]{2,}$", remainder)
    section = remainder[: next_heading.start()] if next_heading else remainder
    return normalize_whitespace(section)
