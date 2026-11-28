"""Pure metric functions for the three test levels (RAGOps part B). Standard library only."""

from __future__ import annotations

import math
import random
from typing import Any


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def max_abs_diff(a: list[float], b: list[float]) -> float:
    return max((abs(x - y) for x, y in zip(a, b)), default=0.0)


def matches(chunk: dict[str, Any], entry: dict[str, Any], tolerance: int = 1) -> bool:
    """Does a retrieved chunk hold a relevant passage? Same document, and its page within
    `tolerance` pages of a ground-truth page (a chunk can start a page before its answer)."""
    if chunk.get("source") != entry["doc"] or chunk.get("page") is None:
        return False
    return any(abs(int(chunk["page"]) - p) <= tolerance for p in entry["pages"])


def retrieval_scores(retrieved: list[dict[str, Any]], relevant: list[dict[str, Any]],
                     tolerance: int = 1, ks: tuple[int, ...] = (3, 5)) -> dict[str, float]:
    """recall@k, MRR and nDCG@5 for one question (binary relevance, ranked list as returned)."""
    out: dict[str, float] = {}
    for k in ks:
        hit = {i for i, e in enumerate(relevant)
               if any(matches(c, e, tolerance) for c in retrieved[:k])}
        out[f"recall@{k}"] = len(hit) / len(relevant)
    rank = next((i for i, c in enumerate(retrieved, 1)
                 if any(matches(c, e, tolerance) for e in relevant)), None)
    out["mrr"] = 1.0 / rank if rank else 0.0
    gains = [1.0 if any(matches(c, e, tolerance) for e in relevant) else 0.0
             for c in retrieved[:5]]
    dcg = sum(g / math.log2(i + 1) for i, g in enumerate(gains, 1))
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), 5) + 1))
    out["ndcg@5"] = dcg / ideal if ideal else 0.0
    return out


def typo(text: str, rng: random.Random, words: int = 2) -> str:
    """Swap two neighbouring letters inside `words` longer words: a deterministic typo noise."""
    tokens = text.split()
    candidates = [i for i, t in enumerate(tokens) if len(t) >= 5 and t.isalpha()]
    for i in rng.sample(candidates, min(words, len(candidates))):
        t = tokens[i]
        j = rng.randint(1, len(t) - 3)
        tokens[i] = t[:j] + t[j + 1] + t[j] + t[j + 2:]
    return " ".join(tokens)


def spread(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0
