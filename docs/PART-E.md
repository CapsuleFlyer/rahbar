# Part E — data drift and semantic coverage

## E1 — live query set

`eval/coverage_queries.json` contains 40 live-style questions: 28 in-domain questions
from the D&D rules corpus and 12 out-of-domain questions from unrelated subject areas.
The set records a source and section for each in-domain query and a topic label for
coverage-gap grouping.

## E2 — semantic coverage against the golden set

E2 embeds every live query and every golden question with the configured
`nomic-embed-text` model, then selects the highest cosine similarity for each live
query. This is a semantic comparison against the golden questions, not the separate
top-k document-retrieval diagnostic in `eval/coverage.py`.

The threshold is **0.85 cosine similarity**. The assignment's example uses 85% as a
coverage target; the script therefore reports both the percentage of in-domain queries
at or above 0.85 and whether at least 85% of the in-domain set meets that threshold.
OOD matches are reported separately and are not counted as in-domain coverage.

### Recorded results

| Run | Golden questions | In-domain covered | OOD above threshold | Result |
|---|---:|---:|---:|---|
| Before E4 additions | 45 | 14/28 (50.0%) | 0/12 | FAIL |
| After E4 additions | 51 | 16/28 (57.1%) | 0/12 | FAIL |

The six added questions improved semantic coverage by **2 of 28 queries**, or
**7.1 percentage points**. The 85% target was not reached. The remaining uncovered
queries were grouped into eight topics in the after report. This is reported as a
measured improvement, not as a passing coverage gate.

The original before reports are retained as
`eval/coverage/live-coverage-before.json` and
`eval/coverage/live-coverage-before.md`. The after reports are
`eval/coverage/live-coverage-after.json` and
`eval/coverage/live-coverage-after.md`. The source-aware repair planner writes
`repair-plan.json` and `repair-plan.md`; it intentionally does not fabricate page
numbers or expected answer phrases.

Run E2 after building/loading the evaluation image:

```bash
docker build -t rahbar-eval:dev eval
minikube image load rahbar-eval:dev
make live-coverage
```

The command exits non-zero when coverage is below 85%; a non-zero exit is the expected
outcome for the recorded 57.1% after run, not a tool crash.

## E3 — Batch B data drift

E3 compares the original Part B suite run without Batch B against a second run with
Batch B ingested and the Batch B questions enabled. Keep the original baseline report;
do not overwrite it.

Run the following after the Part A Batch B verification has been captured:

```bash
make batch-load DIR=eval/batch_b/docs
make ingest
make eval-suite-batch-b
make eval-results
```

The dedicated `k8s/eval-job-batch-b.yaml` runs the same Part B suite configuration
(repeat count, seed, delay, API, embedding/LLM configuration and evaluation levels)
with the additional `--batch-b` flag. Its result records
`config.batch_b=true` and the active/total golden-question counts. The regular
`make eval-suite` target remains the no-Batch-B baseline.

After the run, identify the newly created `suite-*.json` and `.md` files in
`eval/results/`. Compare the new report with the preserved no-Batch-B baseline.
Discuss changes in retrieval recall/MRR/nDCG, abstention and answer metrics, and
latency. Any change must be attributed to the additional Batch B questions and
documents only if the two reports otherwise used the same configuration. Record the
actual values from the generated reports; do not estimate or pre-fill them.

## E4 — close the coverage gap

Six additional human-authored questions, g46–g51, were added to
`eval/golden.jsonl` based on gaps found in the first E2 report. They cover
stabilization, ability checks, 2014 opportunity attacks, Long Rest benefits, Fireball
spell level and slow travel pace. `make golden-check` reported:

```
questions=51 answerable=37 unanswerable=5 hard=9 human=20 synthetic_reviewed=8
```

The after E2 run improved from 14/28 to 16/28 in-domain coverage
(+2 queries, or +7.1 percentage points). This satisfies the E4 demonstration:
at least six questions were added and measured coverage increased. It does **not**
meet the separate E2 85% coverage target.

A reproducible comparison is generated with:

```bash
make e4-report
```

The target compares `eval/coverage/live-coverage-before.json` with
`eval/coverage/live-coverage-after.json`, and compares the preserved 45-question
snapshot `eval/golden-before-e4.jsonl` with the current
`eval/golden.jsonl`. It writes `eval/coverage/e4-comparison.json` and
`eval/coverage/e4-comparison.md`. The script fails if fewer than six questions
were added, the live-query sets or thresholds differ, or coverage did not increase.
It reports the E2 85% gate separately so E4 success is not misrepresented as an E2
gate pass.

The six entries' source pages and expected phrases still require content-level
verification against the cited source documents; the golden-set linter verifies
that references are present, not that their contents are factually correct.

## Errata and official-ruling investigation

Live queries for the 2021 Player's Handbook, 2021 Dungeon Master's Guide and 2018
Monster Manual errata retrieved their corresponding PDFs, but the API abstained and
returned no citations. Retrieved section text included visibly garbled OCR
(e.g. the Dungeon Master's Guide title was repeated as corrupted characters). This is
evidence of a document extraction/OCR quality limitation, not proof that the errata
contain no corrections. These queries should remain documented as unresolved until
the scans are OCR-processed and their relevant passages verified.

The Sage Advice Compendium query was answered from context with high confidence and
three citations to page 1 sections (the document introduction, Official Rulings and
The Role of Rules). It should be treated as covered by the current corpus.

## Reproducibility and evidence checklist

- [ ] E1: retain `eval/coverage_queries.json` showing 28 in-domain and 12 OOD queries.
- [ ] E2: retain before/after JSON and Markdown reports and the repair plan.
- [ ] E3: retain the ingestion verification report and the Batch B-enabled suite JSON/Markdown report.
- [ ] E4: retain `eval/golden-before-e4.jsonl`, the 51-question `eval/golden.jsonl`, `make golden-check` output, before/after coverage reports and the `make e4-report` comparison.
- [ ] Include the unresolved 85% E2 gate and errata OCR limitation in the final discussion; do not describe either as passed.
