#!/usr/bin/env python3
"""Check eval/golden.jsonl against the handout's rules for the golden set (RAGOps part B).

    python eval/golden_lint.py            # exit 1 while a rule is not met

Rules: at least 25 questions; 15 answerable (each with a ground-truth document and page); 5
unanswerable; 5 hard; 8 written by hand (label human); every question labelled human or
synthetic; and 8 synthetic questions reviewed by hand (reviewed: true).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MINIMUMS = {"questions": 25, "answerable": 15, "unanswerable": 5, "hard": 5, "human": 8,
            "synthetic_reviewed": 8}


def lint(path: Path) -> tuple[dict[str, int], list[str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    problems: list[str] = []
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        problems.append("duplicate question ids")
    for r in rows:
        if r.get("label") not in ("human", "synthetic"):
            problems.append(f"{r['id']}: label must be human or synthetic")
        if r["type"] not in ("answerable", "unanswerable", "hard"):
            problems.append(f"{r['id']}: unknown type {r['type']!r}")
        needs_truth = r["type"] != "unanswerable"
        if needs_truth and not all(e.get("doc") and e.get("pages") for e in r.get("relevant", [])):
            problems.append(f"{r['id']}: needs a ground-truth document and page")
        if needs_truth and not r.get("relevant"):
            problems.append(f"{r['id']}: no relevant passage listed")
        if r["type"] == "unanswerable" and r.get("relevant"):
            problems.append(f"{r['id']}: an unanswerable question must not list passages")
    counts = {
        "questions": len(rows),
        "answerable": sum(r["type"] == "answerable" for r in rows),
        "unanswerable": sum(r["type"] == "unanswerable" for r in rows),
        "hard": sum(r["type"] == "hard" for r in rows),
        "human": sum(r.get("label") == "human" for r in rows),
        "synthetic_reviewed": sum(r.get("label") == "synthetic" and r.get("reviewed") is True
                                  for r in rows),
    }
    for key, need in MINIMUMS.items():
        if counts[key] < need:
            problems.append(f"{key}: {counts[key]} (need {need})")
    return counts, problems


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "golden.jsonl"
    counts, problems = lint(path)
    print("  ".join(f"{k}={v}" for k, v in counts.items()))
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
