# RAGOps test suite 20261128T082206Z

golden questions: 35 of 39 (Batch B included: False) · runs: 2 · seed 42 · page tolerance ±1

| Level | Metric | Value | Spread between runs |
| --- | --- | ---: | ---: |
| module | paraphrase mean cosine | 0.867 | 0.000 |
| module | unrelated mean cosine | 0.585 | 0.000 |
| module | gap (paraphrase minus unrelated) | 0.282 | 0.000 |
| module | paraphrase beats unrelated (pairs) | 100.0% | 0.000 |
| module | embedding time per chunk (ms) | 272.011 | 116.876 |
| module | determinism: largest difference | 0.000 | 0.000 |
| component | recall@3 | 0.883 | 0.000 |
| component | recall@3 change with typos | -0.333 | 0.000 |
| component | recall@5 | 0.917 | 0.000 |
| component | recall@5 change with typos | -0.333 | 0.000 |
| component | MRR | 0.784 | 0.000 |
| component | MRR change with typos | -0.266 | 0.000 |
| component | nDCG@5 | 0.979 | 0.000 |
| component | nDCG@5 change with typos | -0.293 | 0.000 |
| e2e | abstention correctness | 100.0% | 0.000 |
| e2e | false abstentions on answerable | 100.0% | 0.000 |
| e2e | latency p50 (s) | 0.504 | 0.009 |
| e2e | latency p95 (s) | 0.618 | 0.036 |

recall@5 by question kind:

| Kind | Questions | recall@5 | MRR |
| --- | ---: | ---: | ---: |
| exact | 5 | 0.800 | 0.667 |
| injection | 1 | 1.000 | 1.000 |
| multi-chunk | 2 | 0.750 | 0.750 |
| older-edition | 2 | 1.000 | 0.667 |
| ordinary | 16 | 0.938 | 0.846 |
| paraphrase | 2 | 1.000 | 0.417 |
| version | 4 | 1.000 | 0.833 |
