# RAGOps test suite 20261128T081703Z

golden questions: 35 of 39 (Batch B included: False) · runs: 2 · seed 42 · page tolerance ±1

| Level | Metric | Value | Spread between runs |
| --- | --- | ---: | ---: |
| module | paraphrase mean cosine | 0.867 | 0.000 |
| module | unrelated mean cosine | 0.585 | 0.000 |
| module | gap (paraphrase minus unrelated) | 0.282 | 0.000 |
| module | paraphrase beats unrelated (pairs) | 100.0% | 0.000 |
| module | embedding time per chunk (ms) | 286.442 | 72.843 |
| module | determinism: largest difference | 0.000 | 0.000 |
| component | recall@3 | 0.683 | 0.000 |
| component | recall@3 change with typos | -0.283 | 0.000 |
| component | recall@5 | 0.683 | 0.000 |
| component | recall@5 change with typos | -0.283 | 0.000 |
| component | MRR | 0.700 | 0.000 |
| component | MRR change with typos | -0.267 | 0.000 |
| component | nDCG@5 | 0.687 | 0.000 |
| component | nDCG@5 change with typos | -0.280 | 0.000 |
| e2e | abstention correctness | 100.0% | 0.000 |
| e2e | false abstentions on answerable | 100.0% | 0.000 |
| e2e | latency p50 (s) | 0.492 | 0.005 |
| e2e | latency p95 (s) | 0.869 | 0.631 |

recall@5 by question kind:

| Kind | Questions | recall@5 | MRR |
| --- | ---: | ---: | ---: |
| exact | 5 | 0.600 | 0.600 |
| injection | 1 | 1.000 | 1.000 |
| multi-chunk | 2 | 0.250 | 0.500 |
| older-edition | 2 | 0.500 | 0.500 |
| ordinary | 16 | 0.812 | 0.812 |
| paraphrase | 2 | 0.000 | 0.000 |
| version | 4 | 0.750 | 0.750 |
