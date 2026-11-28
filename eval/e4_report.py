#!/usr/bin/env python3
"""Build a reproducible Part E4 before/after coverage comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compare_e4(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    before_golden: list[dict[str, Any]],
    after_golden: list[dict[str, Any]],
) -> dict[str, Any]:
    before_by_id = {row["id"]: row for row in before_golden}
    after_by_id = {row["id"]: row for row in after_golden}
    if len(before_by_id) != len(before_golden) or len(after_by_id) != len(after_golden):
        raise ValueError("Golden question IDs must be unique")

    added_ids = sorted(set(after_by_id) - set(before_by_id))
    removed_ids = sorted(set(before_by_id) - set(after_by_id))
    if removed_ids:
        raise ValueError("E4 comparison cannot remove baseline questions: " + ", ".join(removed_ids))

    before_total = before_report["counts"]["in"]
    after_total = after_report["counts"]["in"]
    before_covered = before_report["in_domain_covered"]
    after_covered = after_report["in_domain_covered"]
    if before_total != after_total:
        raise ValueError("Before/after reports must use the same in-domain live-query count")
    if before_report["threshold"] != after_report["threshold"]:
        raise ValueError("Before/after reports must use the same cosine threshold")
    if before_report["live_queries"] != after_report["live_queries"]:
        raise ValueError("Before/after reports must use the same live-query set")
    if before_report["counts"] != after_report["counts"]:
        raise ValueError("Before/after reports must use identical in/out query counts")

    delta = after_covered - before_covered
    return {
        "requirement": "E4",
        "added_question_count": len(added_ids),
        "added_question_ids": added_ids,
        "added_questions": [{"id": key, "question": after_by_id[key]["question"]} for key in added_ids],
        "before": {
            "golden_questions": len(before_golden),
            "covered": before_covered,
            "total": before_total,
            "coverage": before_covered / before_total if before_total else 0.0,
        },
        "after": {
            "golden_questions": len(after_golden),
            "covered": after_covered,
            "total": after_total,
            "coverage": after_covered / after_total if after_total else 0.0,
        },
        "coverage_increase_queries": delta,
        "coverage_increase_percentage_points": (delta / before_total * 100) if before_total else 0.0,
        "threshold": after_report["threshold"],
        "e4_six_questions_requirement_met": len(added_ids) >= 6,
        "coverage_increased": delta > 0,
        "e2_coverage_gate_passed_after_e4": after_report.get("gate_passed", False),
        "e4_demonstration_passed": len(added_ids) >= 6 and delta > 0,
    }


def render_markdown(result: dict[str, Any]) -> str:
    before = result["before"]
    after = result["after"]
    lines = [
        "# Part E4 — golden-set expansion and coverage comparison",
        "",
        f"- New golden questions: {result['added_question_count']} ({', '.join(result['added_question_ids'])})",
        f"- Cosine threshold: {result['threshold']:.2f}",
        f"- Before: {before['covered']}/{before['total']} ({before['coverage']:.1%}) across {before['golden_questions']} golden questions",
        f"- After: {after['covered']}/{after['total']} ({after['coverage']:.1%}) across {after['golden_questions']} golden questions",
        f"- Coverage change: +{result['coverage_increase_queries']} queries (+{result['coverage_increase_percentage_points']:.1f} percentage points)",
        "",
        "## Added questions",
        "",
        "| ID | Question |",
        "|---|---|",
    ]
    for row in result["added_questions"]:
        lines.append(f"| {row['id']} | {row['question']} |")
    lines += [
        "",
        "## Outcome",
        "",
        f"- Six-question requirement: {'MET' if result['e4_six_questions_requirement_met'] else 'NOT MET'}",
        f"- Coverage increase: {'DEMONSTRATED' if result['coverage_increased'] else 'NOT DEMONSTRATED'}",
        f"- E4 demonstration: {'PASS' if result['e4_demonstration_passed'] else 'FAIL'}",
        f"- E2 85% coverage gate after E4: {'PASS' if result['e2_coverage_gate_passed_after_e4'] else 'FAIL'}",
        "",
        "E4 passes when at least six new golden questions are added and the measured in-domain coverage increases. This does not imply that the separate E2 85% coverage gate passes.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-report", type=Path, default=Path("eval/coverage/live-coverage-before.json"))
    parser.add_argument("--after-report", type=Path, default=Path("eval/coverage/live-coverage-after.json"))
    parser.add_argument("--before-golden", type=Path, default=Path("eval/golden-before-e4.jsonl"))
    parser.add_argument("--after-golden", type=Path, default=Path("eval/golden.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("eval/coverage/e4-comparison.json"))
    args = parser.parse_args()

    result = compare_e4(
        json.loads(args.before_report.read_text(encoding="utf-8")),
        json.loads(args.after_report.read_text(encoding="utf-8")),
        read_jsonl(args.before_golden),
        read_jsonl(args.after_golden),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    markdown_path = args.out.with_suffix(".md")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    print(f"New golden questions: {result['added_question_count']}")
    print(f"Coverage: {result['before']['covered']}/{result['before']['total']} -> {result['after']['covered']}/{result['after']['total']}")
    print(f"Coverage increase: +{result['coverage_increase_percentage_points']:.1f} percentage points")
    print("E4 demonstration: " + ("PASS" if result["e4_demonstration_passed"] else "FAIL"))
    print("E2 85% gate after E4: " + ("PASS" if result["e2_coverage_gate_passed_after_e4"] else "FAIL"))
    print(f"Reports: {args.out} and {markdown_path}")
    return 0 if result["e4_demonstration_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
