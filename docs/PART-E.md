# Part E — corpus coverage and drift

## Coverage set

`eval/coverage_queries.json` contains 40 live-style questions: 28 in-domain questions grounded
in the committed corpus and 12 out-of-domain questions. Each in-domain row names its expected
source and, where applicable, section. The set includes current and superseded rule versions,
the errata and Sage Advice sources, and known absent topics.

## Run the coverage test

Start the API/cluster and expose it at the local endpoint. For the cluster port-forward workflow:

```bash
kubectl -n rahbar port-forward deploy/api 8000:8000
```

In another terminal:

```bash
python3 eval/coverage.py --api http://127.0.0.1:8000 --host rahbar.local --out eval/coverage/before.json
```

The script calls only `POST /api/retrieve`; it does not call the LLM. It writes JSON and Markdown
reports, groups missed in-domain questions by topic, and exits nonzero when in-domain coverage
is below 75% or more than 50% of out-of-domain questions produce a top similarity at or above
the API relevance floor. The out-of-domain metric is a high-similarity retrieval rate, not proof
that the answer generator would answer incorrectly.

## Corpus drift run

Keep the original report as the before snapshot. Make a documented, reversible corpus change
(e.g. remove or replace one source document in a separate test copy), load that changed corpus
into the test environment and run the indexer. Do not change the production corpus or overwrite
the before report.

```bash
python3 eval/coverage.py --api http://127.0.0.1:8000 --host rahbar.local --out eval/coverage/after-drift.json
python3 eval/coverage.py --compare eval/coverage/before.json eval/coverage/after-drift.json
```

The comparison requires identical query IDs and reports the coverage delta plus newly covered
and newly uncovered questions. Record the exact corpus change, ingestion report, and both
coverage reports as evidence. Restore the original corpus and re-index after the experiment.

## Golden-set additions

Six manually authored questions (g40–g45) extend the existing golden set without changing its
39 existing entries. Their source/page labels are grounded in the corpus and checked by
`make golden-check`.

## Version intent correction

The current corpus edition is SRD 5.2.1 (2024). A question explicitly naming 2024 must not
enable superseded 2014 chunks. Questions naming earlier years, or explicitly asking for a
previous/superseded version, still enable them. Regression tests cover both cases.
