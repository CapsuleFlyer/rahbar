"""Retrieval rail (RAGOps D4): spot prompt-injection attempts in the question and in retrieved text.

The DEFENCE is in services/prompt.py and services/grounding.py and always applies: evidence is
delimited, markup inside it is escaped, the model must answer in a fixed schema, and every
citation is checked against what was retrieved. This module only DETECTS and RECORDS: each hit
becomes a guardrail action in the trace and a Prometheus count, so an attack is visible
afterwards instead of silently absorbed.

Nothing here passes text to eval, exec or SQL. Patterns are plain regular expressions.
"""

from __future__ import annotations

import re

_PATTERNS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"\b(?:ignore|disregard|forget|override)\b.{0,40}"
        r"\b(?:previous|prior|above|earlier|all|your)\b.{0,40}"
        r"\b(?:instruction|prompt|rule|message)s?\b", re.I | re.S),
    "reveal_prompt": re.compile(
        r"\b(?:reveal|print|show|repeat|output|leak)\b.{0,30}"
        r"\b(?:system prompt|your instructions|hidden prompt|initial prompt)\b", re.I | re.S),
    "role_override": re.compile(r"\byou are now\b|\bpretend (?:to be|you are)\b", re.I),
    "new_instructions": re.compile(r"\b(?:new|updated|revised) instructions?\s*:", re.I),
    "delimiter_forgery": re.compile(r"</?\s*(?:evidence|question|system)\b", re.I),
}


def scan(text: str) -> list[str]:
    """Names of the injection patterns found in `text`, in a stable order (empty = none)."""
    return [name for name, pattern in _PATTERNS.items() if pattern.search(text or "")]
