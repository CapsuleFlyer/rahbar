#!/usr/bin/env python3
"""Summarise the trace log over a time window (RAGOps D3). Standard library only.

    python scripts/trace_report.py [FILE ...|-] [--since 24h] [--until ISO] [--json]
    make trace-report SINCE=1h

Reports: query count, cache hit rate, abstention rate, fallbacks, the distribution of the
best retrieved similarity (top-1), p50 and p95 latency for each stage, and the number of
injection attempts flagged by the guardrail.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

BUCKETS = [0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
STAGES = ["embed", "cache", "retrieve", "generate", "total"]


def parse_when(text: str, now: datetime) -> datetime:
    m = re.fullmatch(r"(\d+)\s*([smhd])", text.strip())
    if m:
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return now - timedelta(**{unit: int(m.group(1))})
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def read(paths: list[str]) -> Iterable[dict[str, Any]]:
    for path in paths:
        handle = sys.stdin if path == "-" else open(path, encoding="utf-8")
        with handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("msg") == "trace":
                    yield rec


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    seen: dict[str, dict[str, Any]] = {}
    for r in records:                      # the same trace can be read twice (stdout + file)
        seen[str(r.get("trace_id"))] = r
    records = list(seen.values())
    n = len(records)
    outcomes = [str(r.get("outcome")) for r in records]
    cache = [(r.get("cache") or {}).get("result") for r in records]
    hits, misses = cache.count("hit"), cache.count("miss")
    top1 = [float(r["retrieved"][0]["score"]) for r in records if r.get("retrieved")]
    lat: dict[str, dict[str, float | None]] = {}
    for stage in STAGES:
        vals = [float((r.get("latency_ms") or {})[stage]) for r in records
                if stage in (r.get("latency_ms") or {})]
        lat[stage] = {"n": len(vals), "p50": percentile(vals, 50), "p95": percentile(vals, 95)}
    flagged = [g for r in records for g in (r.get("guardrails") or [])
               if g.get("rail") == "injection_scan"]
    dist = {f"{lo:.1f}-{min(hi, 1.0):.1f}": sum(1 for s in top1 if lo <= s < hi)
            for lo, hi in zip(BUCKETS, BUCKETS[1:])}
    return {
        "queries": n,
        "cache": {"hits": hits, "misses": misses,
                  "hit_rate": hits / (hits + misses) if hits + misses else None},
        "abstentions": sum(o.startswith("abstained") for o in outcomes),
        "abstention_rate": sum(o.startswith("abstained") for o in outcomes) / n if n else None,
        "fallbacks": sum(o.startswith("fallback") for o in outcomes),
        "top1_similarity": {"n": len(top1), "min": min(top1, default=None),
                            "p50": percentile(top1, 50), "p95": percentile(top1, 95),
                            "max": max(top1, default=None), "histogram": dist},
        "latency_ms": lat,
        "injection": {"flags": len(flagged),
                      "queries_with_a_flag": sum(
                          1 for r in records if any(g.get("rail") == "injection_scan"
                                                    for g in (r.get("guardrails") or [])))},
    }


def render(s: dict[str, Any], since: datetime, until: datetime) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{100 * x:.1f}%"

    def num(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    out = [f"TRACE REPORT  {since:%Y-%m-%d %H:%M}Z -> {until:%Y-%m-%d %H:%M}Z",
           f"queries            {s['queries']}",
           f"cache hit rate     {pct(s['cache']['hit_rate'])}  "
           f"({s['cache']['hits']} hits, {s['cache']['misses']} misses)",
           f"abstention rate    {pct(s['abstention_rate'])}  ({s['abstentions']} abstained)",
           f"fallbacks          {s['fallbacks']}",
           f"injection flagged  {s['injection']['flags']} flag(s) on "
           f"{s['injection']['queries_with_a_flag']} quer(ies)",
           "", "top-1 retrieval similarity "
           f"(n={s['top1_similarity']['n']}, min {num(s['top1_similarity']['min'])}, "
           f"p50 {num(s['top1_similarity']['p50'])}, max {num(s['top1_similarity']['max'])})"]
    biggest = max(s["top1_similarity"]["histogram"].values(), default=0) or 1
    for label, count in s["top1_similarity"]["histogram"].items():
        out.append(f"  {label}  {'#' * round(30 * count / biggest):<30} {count}")
    out += ["", "latency per stage (ms)      n     p50     p95"]
    for stage, v in s["latency_ms"].items():
        p50 = "n/a" if v["p50"] is None else f"{v['p50']:.1f}"
        p95 = "n/a" if v["p95"] is None else f"{v['p95']:.1f}"
        out.append(f"  {stage:<22} {v['n']:>5} {p50:>7} {p95:>7}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("files", nargs="*", help="trace files, or - for stdin")
    ap.add_argument("--since", default="24h", help="30m, 2h, 7d or an ISO time (default 24h)")
    ap.add_argument("--until", default=None, help="ISO time (default: now)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    files = args.files or sorted(glob.glob("traces/*.jsonl"))
    if not files:
        print("no trace files: pass FILE(s), '-' for stdin, or put *.jsonl under traces/")
        return 2
    now = datetime.now(timezone.utc)
    since = parse_when(args.since, now)
    until = parse_when(args.until, now) if args.until else now + timedelta(minutes=1)
    window = [r for r in read(files)
              if since <= datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00")) <= until]
    summary = summarise(window)
    print(json.dumps(summary, indent=2) if args.json else render(summary, since, until))
    return 0 if window else 1


if __name__ == "__main__":
    raise SystemExit(main())
