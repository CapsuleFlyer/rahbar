#!/usr/bin/env python3
"""Build a source-aware repair plan from a Part E2 semantic coverage report.

This tool never writes unverified questions into golden.jsonl. The live-query
dataset does not provide page numbers or authoritative expected answer phrases.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_plan(report: dict[str, Any], query_data: dict[str, Any],
               golden: list[dict[str, Any]]) -> dict[str, Any]:
    queries = {row["id"]: row for row in query_data["queries"]}
    golden_questions = {normalize(row["question"]) for row in golden}
    candidates = []

    for result in report.get("rows", []):
        if result.get("scope") != "in" or result.get("covered"):
            continue
        source = queries.get(result["id"], {})
        question = source.get("question", result.get("question", ""))
        candidates.append({
            "live_id": result["id"],
            "topic": source.get("topic", result.get("topic", "uncategorized")),
            "question": question,
            "source": source.get("source", ""),
            "section": source.get("section", ""),
            "nearest_golden_id": result.get("best_golden_id"),
            "nearest_golden_question": result.get("best_golden_question"),
            "similarity": result.get("similarity"),
            "exact_duplicate": normalize(question) in golden_questions,
            "relevant": [],
            "expected": [],
            "status": "needs_source_page_and_expected_answer_review",
        })

    candidates.sort(key=lambda row: (
        row["exact_duplicate"],
        row["similarity"] if row["similarity"] is not None else 1.0,
        row["topic"], row["live_id"],
    ))
    topics: dict[str, list[str]] = {}
    for row in candidates:
        topics.setdefault(row["topic"], []).append(row["live_id"])

    return {
        "threshold": report.get("threshold"),
        "minimum_in_domain_coverage": report.get("minimum_in_domain_coverage"),
        "current_coverage": report.get("in_domain_coverage", 0.0),
        "covered": report.get("in_domain_covered", 0),
        "in_domain_total": report.get("counts", {}).get("in", 0),
        "golden_count": len(golden),
        "candidate_count": len(candidates),
        "uncovered_topics": topics,
        "candidates": candidates,
        "limitations": [
            "A semantic miss is not automatically a missing knowledge topic; inspect its nearest golden question.",
            "The live-query dataset supplies a source filename and section, but not a verified page number.",
            "Expected answer phrases must be checked against the cited source passage.",
            "Do not add candidates marked as duplicates without a distinct information need.",
        ],
    }


def render_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# E2 coverage repair plan", "",
        f"- Current semantic coverage: {plan['covered']}/{plan['in_domain_total']} ({plan['current_coverage']:.1%})",
        f"- Similarity threshold: {plan['threshold']:.2f}",
        f"- Existing golden questions: {plan['golden_count']}",
        f"- Uncovered candidates: {plan['candidate_count']}", "",
        "This is a review plan, not an automatic golden-set update. Verify source pages "
        "and expected answer phrases before adding any candidate.", "",
        "## Candidates, lowest similarity first", "",
        "| Live ID | Topic | Similarity | Source | Section | Exact duplicate? |",
        "|---|---|---:|---|---|---|",
    ]
    for row in plan["candidates"]:
        score = "" if row["similarity"] is None else f"{row['similarity']:.3f}"
        lines.append(
            f"| {row['live_id']} | {row['topic']} | {score} | {row['source']} | "
            f"{row['section']} | {'yes' if row['exact_duplicate'] else 'no'} |"
        )
    lines += ["", "## Candidate details", ""]
    for row in plan["candidates"]:
        lines += [
            f"### {row['live_id']} — {row['topic']}", "",
            f"- Proposed question: {row['question']}",
            f"- Source: {row['source']} — section: {row['section']}",
            f"- Nearest golden: {row['nearest_golden_id']} — {row['nearest_golden_question']}",
            f"- Similarity: {row['similarity']}",
            f"- Exact duplicate: {'yes' if row['exact_duplicate'] else 'no'}",
            "- Required: verify the page number and expected answer phrases from the source.", "",
        ]
    lines += ["## Review rules", ""]
    lines.extend(f"- {item}" for item in plan["limitations"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("eval/coverage/live-coverage-after.json"))
    parser.add_argument("--queries", type=Path, default=Path("eval/coverage_queries.json"))
    parser.add_argument("--golden", type=Path, default=Path("eval/golden.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=Path("eval/coverage"))
    args = parser.parse_args()

    plan = build_plan(load_json(args.report), load_json(args.queries), load_jsonl(args.golden))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "repair-plan.json"
    markdown_path = args.out_dir / "repair-plan.md"
    json_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(plan), encoding="utf-8")
    print(f"Current coverage: {plan['covered']}/{plan['in_domain_total']} ({plan['current_coverage']:.1%})")
    print(f"Uncovered candidates: {plan['candidate_count']}")
    print(f"Topics needing review: {len(plan['uncovered_topics'])}")
    print(f"Repair plan: {markdown_path} and {json_path}")
    print("Golden set unchanged: source pages and expected phrases require verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
