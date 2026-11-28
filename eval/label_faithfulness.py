#!/usr/bin/env python3
"""Label answers by hand for the faithfulness check (RAGOps part B, end-to-end level).

    python eval/label_faithfulness.py eval/results/suite-<run>.json [--n 10]

Shows each answered question's answer next to the evidence the model was shown (fetched
again with the trace tool) and asks whether the answer is supported. Your labels go to
eval/faithfulness_labels.json; the suite then reports how often its LLM judge agrees with you.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()
    report = json.loads(Path(args.report).read_text())
    golden = {json.loads(line)["id"]: json.loads(line) for line in
              (HERE / "golden.jsonl").read_text().splitlines() if line.strip()}
    rows = [r for r in report["runs"][0]["e2e"]["per_question"] if r["answered"]][: args.n]
    store = HERE / "faithfulness_labels.json"
    labels = json.loads(store.read_text()) if store.exists() else {}
    for r in rows:
        print("=" * 78)
        print(f"{r['id']}  {golden[r['id']]['question']}")
        print(f"trace id: {r['trace_id']}   (make trace ID=<that id> shows the exact evidence)")
        print(f"judge said: {'supported' if r['faithful'] else 'NOT supported'}")
        answer = input("Is the answer fully supported by the evidence? [y/n/skip] ").strip().lower()
        if answer in ("y", "n"):
            labels[r["id"]] = {"supported": answer == "y", "trace_id": r["trace_id"]}
    store.write_text(json.dumps(labels, indent=2) + "\n")
    print(f"{len(labels)} labels saved to {store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
