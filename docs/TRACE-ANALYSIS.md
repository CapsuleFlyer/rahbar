# Trace analysis (Part D)

The trace implementation, reconstruction tool, and trace report are exercised by
`api/tests/test_trace.py`. The committed sample in `traces/sample-2026-11-23.jsonl`
contains real API traces; the example below uses an actual abstention, not a fabricated
record.

## Five-line root-cause note

- **Symptom:** RAHBAR abstained on “What is the save DC of a mind flayer's Mind Blast?”
- **Trace:** `6212ddff4024bc2d4a94c9d58aea7fce`, outcome `abstained:model`, prompt hash `4d7c0836f155fb5accd7961dd87bea049217b7a548bd68b946f2ddbc745ddd8b`.
- **Evidence:** Top-1 similarity was 0.7179, above the 0.50 relevance floor, but the retrieved passages were Mind Spike, Bonus Actions, and Rod of Lordly Might; none supplied the Mind Blast save DC.
- **Root cause:** Semantic retrieval admitted related but non-answering passages; the relevance floor did not separate this hard negative, while the model correctly identified that the supplied context lacked the answer and abstained.
- **Action:** Preserve the abstention and citation safeguards; investigate lexical/hybrid retrieval or reranking against hard negatives before changing the relevance floor.

## Reconstructing and reporting traces

Run a query and retain the trace ID printed by the API:

```bash
make ask Q="What is the save DC of a mind flayer's Mind Blast?"
```

Rebuild the exact prompt and inspect the retrieved passages:

```bash
make trace ID=<trace-id>
```

Summarise recent traces, including cache hits, abstentions, fallbacks, top-1
similarity, per-stage p50/p95 latency, and injection flags:

```bash
make trace-report SINCE=24h
```

The trace is persisted as JSON Lines on the trace PVC and also emitted to API stdout.
The sample trace file is evidence from the 2026-11-23 cluster run. The trace report
is a summary of the selected time window; it should be generated from the submission
cluster when capturing final screenshots.
