#!/usr/bin/env python3
"""Compare a verification report with what Batch B planted (eval/batch_b/expected.json).

    python eval/batch_b/check_report.py REPORT.json      # reports/verification-*.json from the lake
    kubectl -n rahbar logs job/<ingest job> | ... (or copy the file out with the ops pod)

Prints, per planted problem, which check caught it and whether the outcome matches. Exit code 1
when something planted was missed: that is a finding for the report (Part G, question a).
"""

import json
import sys
from pathlib import Path

expected = json.loads((Path(__file__).resolve().parent / "expected.json").read_text())
report = json.loads(Path(sys.argv[1]).read_text())
rows = {d["source"]: d for d in report["documents"]}
missed = 0
print(f"{'document':<42}{'planted':<24}{'caught by':<14}{'outcome':<24}result")
for name, want in expected.items():
    got = rows.get(name)
    if got is None:
        print(f"{name:<42}{want['planted']:<24}{'-':<14}{'(not in report)':<24}MISSING")
        missed += 1
        continue
    failed = [n for n, c in got["checks"].items() if not c["passed"]]
    ok = got["outcome"].startswith(want["outcome"])
    if want.get("check") and want["check"] not in failed:
        ok = False
    missed += not ok
    print(f"{name:<42}{want['planted']:<24}{','.join(failed) or '-':<14}{got['outcome']:<24}"
          f"{'ok' if ok else 'DIFFERENT'}")
sys.exit(1 if missed else 0)
