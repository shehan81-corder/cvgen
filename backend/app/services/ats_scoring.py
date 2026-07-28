"""Deterministic ATS keyword-match scoring (spec.md §9). No LLM involved —
runs on full document text so a keyword living in a `fixed`-classified
block (e.g. a tool name in a job title) still counts, per architecture.md §8.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,}")

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "for", "to",
    "of", "in", "on", "at", "by", "with", "from", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "we", "you", "your", "our", "they", "their", "will", "would",
    "should", "can", "could", "may", "might", "must", "have", "has", "had",
    "do", "does", "did", "not", "no", "so", "than", "such", "into", "about",
    "across", "per", "etc", "including", "include", "includes", "who",
    "what", "when", "where", "which", "while", "all", "any", "each",
    "other", "more", "most", "some", "up", "out", "over", "under", "how",
}


def _stem(word: str) -> str:
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def extract_keywords(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    return {_stem(t) for t in tokens if t not in _STOPWORDS and len(t) >= 2}


def match_score(job_description: str, document_text: str) -> float:
    """Percentage of job-description keywords present in document_text."""
    jd_keywords = extract_keywords(job_description)
    if not jd_keywords:
        return 0.0
    doc_keywords = extract_keywords(document_text)
    matched = jd_keywords & doc_keywords
    return round(100 * len(matched) / len(jd_keywords), 1)
