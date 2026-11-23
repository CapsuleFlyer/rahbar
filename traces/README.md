# Traces

One JSON line per query, written by the api pods. Sample traces from real runs on the cluster
are committed here for the report.

Create them from your own cluster (never write these by hand):

```bash
make ask Q="What DC does the Hide action need?"          # prints "trace: <id>"
kubectl -n rahbar exec deploy/api -- sh -c 'cat /traces/*.jsonl' > traces/sample-$(date +%F).jsonl
make trace ID=<id>                                        # the context and prompt behind that answer
make trace-report SINCE=1h                                # cache hit rate, abstentions, latencies...
```

Each line has `trace_id` (the reply's `request_id`), the query, the embedding model, the
collection and index id, every retrieved chunk with document id, version and score, the
filters, the order sent to the model, the full prompt and its SHA-256, model parameters, the
response and citations, guardrail actions, per-stage latency and the cache result.
