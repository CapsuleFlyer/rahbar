# Part C — Controlled top-k experiment

## Change under test

The experiment changes only `TOP_K`, the number of retrieved passages supplied to generation. The embedding model, indexed collection, corpus, prompt, LLM, relevance floor, cache policy and golden set remain fixed. No re-index is required.

The baseline is `TOP_K=5`. The deliberately restrictive candidate is `TOP_K=1`; the higher-context candidate is `TOP_K=8`. All three runs use the same 35-question golden set, fixed seed, two repeats and all three evaluation levels.

The component evaluator sends the configured top-k to `POST /api/retrieve`. The end-to-end evaluator uses the API's ConfigMap value through `POST /api/ask`. The module-level embedding tests are expected to remain unchanged because top-k does not affect embeddings.

## Build the updated evaluator image

After pulling the Part C changes:

```bash
docker build -t rahbar-eval:dev eval
minikube image load rahbar-eval:dev
```

## Run baseline and candidates

Run each command from the repository root with the dev Kubernetes context active:

```bash
bash scripts/run-suite-experiment.sh run baseline 5
bash scripts/run-suite-experiment.sh run top-k-1 1
bash scripts/run-suite-experiment.sh run top-k-8 8
```

Each run patches only `TOP_K` in `rahbar-config`, restarts the API, clears Redis, starts a uniquely named copy of the evaluation Job and copies its JSON/Markdown report into `eval/experiments/`.

## Release gate

The thresholds live in `eval/experiment_thresholds.json`; the gate is implemented by `eval/experiment_gate.py`. It compares candidate metrics against the fresh baseline and exits 0 for PASS or 1 for FAIL.

```bash
.venv/bin/python eval/experiment_gate.py \
  --baseline eval/experiments/baseline.json \
  --candidate eval/experiments/top-k-1.json \
  --json-out eval/experiments/top-k-1-gate.json

.venv/bin/python eval/experiment_gate.py \
  --baseline eval/experiments/baseline.json \
  --candidate eval/experiments/top-k-8.json \
  --json-out eval/experiments/top-k-8-gate.json
```

The gate requires all three levels, the same embedding/LLM configuration and the same active golden-question count. It limits retrieval and answer-quality regressions, requires valid citations and correct abstention, and limits p95 latency growth to 25%.

## Restore

```bash
bash scripts/run-suite-experiment.sh restore
```

This restores the baseline `TOP_K=5` without rebuilding an image or re-indexing.

## Results to record

The measured reports and gate decisions are saved as:

- `eval/experiments/baseline.json` and `.md`
- `eval/experiments/top-k-1.json` and `.md`
- `eval/experiments/top-k-8.json` and `.md`
- `eval/experiments/top-k-1-gate.json`
- `eval/experiments/top-k-8-gate.json`

Do not write expected or fabricated metric values into the report. Record the actual values from these generated files, then state whether the top-k=1 candidate was rejected and whether top-k=8 was accepted. If top-k=8 fails, test a middle value (for example 6) and retain its actual gate result.
