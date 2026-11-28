#!/usr/bin/env python3
"""Run Part E's 40 live-style questions against the retrieval-only API."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_QUERIES = HERE / "coverage_queries.json"


def post_retrieve(api: str, question: str, k: int, host: str, timeout: int) -> dict:
    payload = json.dumps({"question": question, "k": k}).encode()
    request = urllib.request.Request(
        api.rstrip("/") + "/api/retrieve",
        data=payload,
        headers={"Content-Type": "application/json", "Host": host},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def matches(row: dict, chunk: dict) -> bool:
    if row["source"] and chunk.get("source", "").lower() != row["source"].lower():
        return False
    wanted = row.get("section", "").strip().lower()
    got = chunk.get("section", "").strip().lower()
    return not wanted or got == wanted or got.startswith(wanted + " ") or got.startswith(wanted + ":")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> int:
    dataset = load_json(Path(args.queries))
    questions = dataset["queries"]
    counts = {"in": 0, "out": 0}
    covered = 0
    false_positive = 0
    uncovered_topics: dict[str, list[str]] = defaultdict(list)
    rows = []
    for row in questions:
        try:
            result = post_retrieve(args.api, row["question"], args.k, args.host, args.timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"ERROR {row['id']}: {exc}", file=sys.stderr)
            return 2
        retrieved = result.get("retrieved") or []
        hit = any(matches(row, chunk) for chunk in retrieved) if row["scope"] == "in" else False
        counts[row["scope"]] += 1
        high = False
        if row["scope"] == "in":
            covered += int(hit)
            if not hit:
                uncovered_topics[row["topic"]].append(row["id"])
        else:
            high = bool(retrieved and retrieved[0].get("score", 0) >= result.get("relevance_floor", 0.5))
            false_positive += int(high)
        rows.append({
            "id": row["id"], "question": row["question"], "scope": row["scope"],
            "topic": row["topic"], "covered": hit if row["scope"] == "in" else None,
            "false_positive": high if row["scope"] == "out" else None,
            "top_score": retrieved[0].get("score") if retrieved else None,
            "retrieved": retrieved,
        })
        status = "COVERED" if hit else ("HIGH-SIMILARITY" if high else
                                      "MISS" if row["scope"] == "in" else "NO-HIGH-HIT")
        print(f"{row['id']} [{status}] {row['question']}")
        time.sleep(args.pause)
    in_rate = covered / counts["in"] if counts["in"] else 0
    out_rate = false_positive / counts["out"] if counts["out"] else 0
    report = {
        "api": args.api, "k": args.k, "query_file": str(Path(args.queries)),
        "total": len(rows), "counts": counts, "in_domain_covered": covered,
        "in_domain_coverage": round(in_rate, 4),
        "out_domain_high_similarity": false_positive,
        "out_domain_false_positive_rate": round(out_rate, 4),
        "thresholds": {"minimum_in_domain_coverage": args.min_coverage,
                       "maximum_out_domain_false_positive_rate": args.max_false_positive},
        "uncovered_topics": {key: values for key, values in sorted(uncovered_topics.items())},
        "rows": rows,
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md = [
        "# Part E corpus coverage", "",
        f"- Questions: {len(rows)} ({counts['in']} in-domain, {counts['out']} out-of-domain)",
        f"- In-domain coverage: {covered}/{counts['in']} ({in_rate:.1%})",
        f"- Out-of-domain high-similarity rate: {false_positive}/{counts['out']} ({out_rate:.1%})",
        f"- Thresholds: coverage >= {args.min_coverage:.0%}; false positives <= {args.max_false_positive:.0%}",
        "", "## Uncovered topics", "",
    ]
    for topic, ids in sorted(uncovered_topics.items()):
        md.append(f"- **{topic}**: {', '.join(ids)}")
    md += ["", "## Query results", "", "| ID | Scope | Topic | Result | Top score |", "|---|---|---|---|---:|"]
    for row in rows:
        result = "covered" if row["covered"] else (
            "high-similarity" if row["false_positive"] else "no high hit"
        )
        score = "" if row["top_score"] is None else f"{row['top_score']:.3f}"
        md.append(f"| {row['id']} | {row['scope']} | {row['topic']} | {result} | {score} |")
    output.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nIn-domain coverage: {covered}/{counts['in']} ({in_rate:.1%})")
    print(f"Out-of-domain high-similarity: {false_positive}/{counts['out']} ({out_rate:.1%})")
    print(f"Uncovered topics: {len(uncovered_topics)}")
    print(f"Report: {output} and {output.with_suffix('.md')}")
    passed = in_rate >= args.min_coverage and out_rate <= args.max_false_positive
    print("COVERAGE GATE: " + ("PASS" if passed else "FAIL"))
    return 0 if passed else 1


def compare(before_path: Path, after_path: Path, output: Path) -> int:
    before, after = load_json(before_path), load_json(after_path)
    before_rows = {r["id"]: r for r in before["rows"]}
    after_rows = {r["id"]: r for r in after["rows"]}
    if before_rows.keys() != after_rows.keys():
        print("Cannot compare: query IDs differ.", file=sys.stderr)
        return 2
    newly_uncovered = sorted(
        key for key, row in before_rows.items()
        if row["scope"] == "in" and row["covered"] and not after_rows[key]["covered"]
    )
    newly_covered = sorted(
        key for key, row in before_rows.items()
        if row["scope"] == "in" and not row["covered"] and after_rows[key]["covered"]
    )
    delta = round(after["in_domain_coverage"] - before["in_domain_coverage"], 4)
    result = {
        "before": str(before_path), "after": str(after_path),
        "coverage_before": before["in_domain_coverage"],
        "coverage_after": after["in_domain_coverage"], "coverage_delta": delta,
        "newly_uncovered": newly_uncovered, "newly_covered": newly_covered,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Coverage: {before['in_domain_coverage']:.1%} -> {after['in_domain_coverage']:.1%} "
          f"({delta:+.1%})")
    print(f"Newly uncovered: {', '.join(newly_uncovered) or 'none'}")
    print(f"Newly covered: {', '.join(newly_covered) or 'none'}")
    print(f"Drift comparison: {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--host", default="rahbar.local")
    parser.add_argument("--queries", default=str(DEFAULT_QUERIES))
    parser.add_argument("--out", default="eval/coverage/before.json")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--pause", type=float, default=0.1)
    parser.add_argument("--min-coverage", type=float, default=0.75)
    parser.add_argument("--max-false-positive", type=float, default=0.50)
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--compare-out", default="eval/coverage/drift-comparison.json")
    args = parser.parse_args()
    if args.compare:
        return compare(Path(args.compare[0]), Path(args.compare[1]), Path(args.compare_out))
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
