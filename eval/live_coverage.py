#!/usr/bin/env python3
"""Part E2: semantic coverage of live queries against the golden-question set."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def embed_texts(ollama: str, model: str, texts: list[str], timeout: int = 180) -> list[list[float]]:
    prefix = "search_query: " if model.startswith("nomic") else ""
    payload = json.dumps({
        "model": model,
        "input": [prefix + text for text in texts],
    }).encode("utf-8")
    request = urllib.request.Request(
        ollama.rstrip("/") + "/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    vectors = result.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise ValueError("Ollama returned an unexpected number of embeddings.")
    return [[float(value) for value in vector] for vector in vectors]


def build_report(
    live_queries: list[dict[str, Any]],
    golden_questions: list[dict[str, Any]],
    live_vectors: list[list[float]],
    golden_vectors: list[list[float]],
    threshold: float,
    model: str,
) -> dict[str, Any]:
    rows = []
    uncovered: dict[str, list[str]] = defaultdict(list)
    in_total = in_covered = out_total = out_above = 0

    for index, query in enumerate(live_queries):
        ranked = []
        for golden_index, golden in enumerate(golden_questions):
            score = cosine(live_vectors[index], golden_vectors[golden_index])
            ranked.append((score, golden_index))
        ranked.sort(key=lambda item: item[0], reverse=True)

        best_score, best_index = ranked[0]
        best_golden = golden_questions[best_index]
        covered = best_score >= threshold
        scope = query["scope"]

        if scope == "in":
            in_total += 1
            in_covered += int(covered)
            if not covered:
                uncovered[query.get("topic", "uncategorized")].append(query["id"])
        elif scope == "out":
            out_total += 1
            out_above += int(covered)
        else:
            raise ValueError(f"Unknown scope for {query.get('id')}: {scope}")

        rows.append({
            "id": query["id"],
            "question": query["question"],
            "scope": scope,
            "topic": query.get("topic", "uncategorized"),
            "covered": covered,
            "best_golden_id": best_golden["id"],
            "best_golden_question": best_golden["question"],
            "similarity": round(best_score, 6),
        })

    return {
        "method": "cosine similarity between each live-query embedding and every golden-question embedding",
        "model": model,
        "threshold": threshold,
        "golden_questions": len(golden_questions),
        "live_queries": len(live_queries),
        "counts": {"in": in_total, "out": out_total},
        "in_domain_covered": in_covered,
        "in_domain_coverage": in_covered / in_total if in_total else 0.0,
        "out_domain_above_threshold": out_above,
        "out_domain_above_threshold_rate": out_above / out_total if out_total else 0.0,
        "minimum_in_domain_coverage": 0.85,
        "uncovered_topics": {topic: ids for topic, ids in sorted(uncovered.items())},
        "rows": rows,
    }


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "# Part E2 — semantic live-query coverage",
        "",
        f"- Embedding model: `{report['model']}`",
        f"- Golden questions compared: {report['golden_questions']}",
        f"- Live queries: {report['live_queries']} ({counts['in']} in-domain, {counts['out']} out-of-domain)",
        f"- Cosine similarity threshold: {report['threshold']:.2f}",
        f"- In-domain coverage: {report['in_domain_covered']}/{counts['in']} ({report['in_domain_coverage']:.1%})",
        f"- Out-of-domain queries above threshold: {report['out_domain_above_threshold']}/{counts['out']} ({report['out_domain_above_threshold_rate']:.1%})",
        "",
        f"The cosine threshold is {report['threshold']:.2f}. The assignment paper gives 0.85 as an example for flagging a coverage gap. The nearest golden question is selected independently for every live query.",
        "",
        "## Uncovered in-domain queries by topic",
        "",
    ]
    if report["uncovered_topics"]:
        for topic, ids in report["uncovered_topics"].items():
            lines.append(f"- **{topic}**: {', '.join(ids)}")
    else:
        lines.append("- None")
    lines += [
        "",
        "## Per-query nearest golden question",
        "",
        "| Live ID | Scope | Topic | Best golden ID | Cosine | Result |",
        "|---|---|---|---|---:|---|",
    ]
    for row in report["rows"]:
        result = "covered" if row["covered"] else "uncovered"
        lines.append(
            f"| {row['id']} | {row['scope']} | {row['topic']} | "
            f"{row['best_golden_id']} | {row['similarity']:.3f} | {result} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", ""))
    parser.add_argument("--model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text"))
    parser.add_argument("--queries", type=Path, default=Path("eval/coverage_queries.json"))
    parser.add_argument("--golden", type=Path, default=Path("eval/golden.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("/results/live-coverage.json"))
    parser.add_argument("--threshold", type=float, default=0.85)
    parser.add_argument("--min-coverage", type=float, default=0.85)
    args = parser.parse_args()

    if not args.ollama:
        parser.error("--ollama or OLLAMA_URL is required")
    if not 0.0 <= args.threshold <= 1.0 or not 0.0 <= args.min_coverage <= 1.0:
        parser.error("thresholds must be between 0 and 1")

    live_data = json.loads(args.queries.read_text(encoding="utf-8"))
    live_queries = live_data["queries"]
    golden_questions = read_jsonl(args.golden)
    if not live_queries or not golden_questions:
        parser.error("both the live-query set and golden set must be non-empty")

    texts = [row["question"] for row in live_queries]
    texts.extend(row["question"] for row in golden_questions)

    try:
        vectors = embed_texts(args.ollama, args.model, texts)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"Embedding request failed: {exc}", file=sys.stderr)
        return 2

    live_vectors = vectors[:len(live_queries)]
    golden_vectors = vectors[len(live_queries):]
    report = build_report(
        live_queries, golden_questions, live_vectors, golden_vectors,
        args.threshold, args.model,
    )
    report["minimum_in_domain_coverage"] = args.min_coverage
    report["gate_passed"] = report["in_domain_coverage"] >= args.min_coverage

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path = args.out.with_suffix(".md")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    print(f"Golden questions: {len(golden_questions)}")
    print(f"Live queries: {len(live_queries)} ({report['counts']['in']} in-domain, {report['counts']['out']} out-of-domain)")
    print(f"Cosine threshold: {args.threshold:.2f}")
    print(f"In-domain semantic coverage: {report['in_domain_covered']}/{report['counts']['in']} ({report['in_domain_coverage']:.1%})")
    print(f"OOD queries above threshold: {report['out_domain_above_threshold']}/{report['counts']['out']} ({report['out_domain_above_threshold_rate']:.1%})")
    print(f"Uncovered topics: {len(report['uncovered_topics'])}")
    print(f"Reports: {args.out} and {markdown_path}")
    print("E2 COVERAGE GATE: " + ("PASS" if report["gate_passed"] else "FAIL"))
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
