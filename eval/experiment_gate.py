"""Compare a candidate's three-level suite report with its baseline and apply thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    base_config = baseline.get("config", {})
    candidate_config = candidate.get("config", {})

    for field in ("embed_model", "llm_model", "batch_b", "levels"):
        if base_config.get(field) != candidate_config.get(field):
            failures.append(f"configuration mismatch: {field}")

    if baseline.get("golden", {}).get("active") != candidate.get("golden", {}).get("active"):
        failures.append("baseline and candidate used different active golden question counts")

    required = thresholds.get("required_levels", [])
    for level in required:
        if level not in base_config.get("levels", []) or level not in candidate_config.get("levels", []):
            failures.append(f"required evaluation level missing: {level}")

    base_summary = baseline.get("summary", {})
    candidate_summary = candidate.get("summary", {})
    for metric, rule in thresholds.get("rules", {}).items():
        before = base_summary.get(metric)
        after = candidate_summary.get(metric)
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            failures.append(f"{metric}: missing numeric baseline or candidate value")
            continue

        if "min" in rule and after < rule["min"]:
            failures.append(f"{metric}: {after:.4f} is below minimum {rule['min']:.4f}")
        if "max" in rule and after > rule["max"]:
            failures.append(f"{metric}: {after:.4f} exceeds maximum {rule['max']:.4f}")
        if "min_delta" in rule and after - before < rule["min_delta"]:
            failures.append(
                f"{metric}: delta {after - before:+.4f} is below allowed {rule['min_delta']:+.4f}"
            )
        if "max_delta" in rule and after - before > rule["max_delta"]:
            failures.append(
                f"{metric}: delta {after - before:+.4f} exceeds allowed {rule['max_delta']:+.4f}"
            )
        if "max_ratio" in rule:
            if before <= 0 or after / before > rule["max_ratio"]:
                failures.append(
                    f"{metric}: candidate/baseline ratio is "
                    f"{after / before if before > 0 else float('inf'):.4f}, "
                    f"limit {rule['max_ratio']:.4f}"
                )

    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=Path("eval/experiment_thresholds.json"),
    )
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    baseline = read_json(args.baseline)
    candidate = read_json(args.candidate)
    thresholds = read_json(args.thresholds)
    passed, failures = evaluate(baseline, candidate, thresholds)

    print(f"Baseline:  {args.baseline}")
    print(f"Candidate: {args.candidate}")
    print(f"Baseline TOP_K:  {baseline.get('config', {}).get('top_k', 'unknown')}")
    print(f"Candidate TOP_K: {candidate.get('config', {}).get('top_k', 'unknown')}")
    if passed:
        print("RELEASE GATE: PASS")
    else:
        print("RELEASE GATE: FAIL")
        for failure in failures:
            print(f"- {failure}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {
                    "passed": passed,
                    "baseline": str(args.baseline),
                    "candidate": str(args.candidate),
                    "failures": failures,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
