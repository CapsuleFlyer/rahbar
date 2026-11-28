"""The RAGOps part B test suite: module (embedding), component (retrieval), end-to-end (answers).

    python -m eval.suite --api http://api:8000 --ollama http://192.168.49.10:11434 --out /results

One command runs everything and writes eval/results/suite-<UTC>.json and a summary table.
In the cluster it runs as a Job (k8s/eval-job.yaml); locally point --api at a port-forward.
The whole suite runs --repeat times (default 2) with a fixed seed, so the report can say how
much each metric moves between identical runs.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from . import metrics as m

HERE = Path(__file__).resolve().parent.parent
LEVELS = ("module", "component", "e2e")


@dataclass
class Config:
    api: str = "http://api:8000"
    host: str = ""
    ollama: str = ""
    model: str = "nomic-embed-text"
    llm_base: str = ""
    llm_model: str = ""
    llm_key: str = ""
    out: Path = HERE / "results"
    golden: Path = HERE / "golden.jsonl"
    pairs: Path = HERE / "embedding_pairs.json"
    labels: Path = HERE / "faithfulness_labels.json"
    levels: tuple[str, ...] = LEVELS
    delay: float = 2.0
    repeat: int = 2
    seed: int = 42
    tolerance: int = 1
    batch_b: bool = False
    run_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))


def load_golden(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def active(questions: list[dict[str, Any]], cfg: Config) -> list[dict[str, Any]]:
    """Batch B questions only count once Batch B has been ingested (--batch-b)."""
    return [q for q in questions if cfg.batch_b or not q.get("batch")]


# ------------------------------------------------------------------ module level
def embed(http: httpx.Client, cfg: Config, texts: list[str], kind: str = "query") -> list[list[float]]:
    prefix = {"query": "search_query: ", "document": "search_document: "}[kind] \
        if cfg.model.startswith("nomic") else ""
    r = http.post(f"{cfg.ollama}/api/embed", json={"model": cfg.model,
                                                    "input": [prefix + t for t in texts]})
    r.raise_for_status()
    return [list(map(float, v)) for v in r.json()["embeddings"]]


def run_module(http: httpx.Client, cfg: Config) -> dict[str, Any]:
    if not cfg.ollama:
        return {"skipped": "no --ollama URL: the embedding model is only reachable inside the cluster"}
    pairs = json.loads(cfg.pairs.read_text(encoding="utf-8"))
    def pair_cosines(rows: list[list[str]]) -> list[float]:
        vecs = embed(http, cfg, [t for row in rows for t in row])
        return [m.cosine(vecs[2 * i], vecs[2 * i + 1]) for i in range(len(rows))]
    para, unrel = pair_cosines(pairs["paraphrase"]), pair_cosines(pairs["unrelated"])
    ranked = [p > u for p in para for u in unrel]
    statements = [s for row in pairs["paraphrase"] for s in row]
    passages = [" ".join(statements[(i + j) % len(statements)] for j in range(12)) for i in range(16)]
    started = time.perf_counter()
    for start in range(0, len(passages), 16):
        embed(http, cfg, passages[start:start + 16], "document")
    ms = 1000 * (time.perf_counter() - started) / len(passages)
    probe = statements[:5]
    first, second = embed(http, cfg, probe), embed(http, cfg, probe)
    return {
        "paraphrase_pairs": len(para), "unrelated_pairs": len(unrel),
        "paraphrase_mean": m.mean(para), "unrelated_mean": m.mean(unrel),
        "gap": (m.mean(para) or 0) - (m.mean(unrel) or 0),
        "paraphrase_min": min(para), "unrelated_max": max(unrel),
        "ranked_correctly": sum(ranked) / len(ranked),
        "ms_per_chunk": ms, "chunk_words_mean": m.mean([len(p.split()) for p in passages]),
        "determinism_max_abs_diff": max(m.max_abs_diff(a, b) for a, b in zip(first, second)),
    }


# ------------------------------------------------------------------ component level
def retrieve(http: httpx.Client, cfg: Config, question: str, k: int = 10) -> list[dict[str, Any]]:
    r = http.post(f"{cfg.api}/api/retrieve", json={"question": question, "k": k})
    r.raise_for_status()
    return list(r.json()["retrieved"])


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("recall@3", "recall@5", "mrr", "ndcg@5")
    out: dict[str, Any] = {k: m.mean([r[k] for r in rows]) for k in keys}
    out["questions"] = len(rows)
    return out


def run_component(http: httpx.Client, cfg: Config, questions: list[dict[str, Any]]) -> dict[str, Any]:
    rng = random.Random(cfg.seed)
    rows: list[dict[str, Any]] = []
    noisy: list[dict[str, Any]] = []
    absent_top1: list[float] = []
    for q in questions:
        got = retrieve(http, cfg, q["question"])
        if not q["relevant"]:
            absent_top1.append(got[0]["score"] if got else 0.0)
            continue
        scores = m.retrieval_scores(got, q["relevant"], cfg.tolerance)
        rows.append({"id": q["id"], "type": q["type"], "tags": q["tags"], **scores,
                     "top1": got[0]["score"] if got else None,
                     "retrieved": [(c["source"], c.get("page")) for c in got[:5]]})
        bad = m.typo(q["question"], rng)
        noisy.append({"id": q["id"], **m.retrieval_scores(retrieve(http, cfg, bad), q["relevant"],
                                                         cfg.tolerance)})
    by_tag: dict[str, Any] = {}
    for tag in sorted({t for r in rows for t in r["tags"]}):
        by_tag[tag] = _aggregate([r for r in rows if tag in r["tags"]])
    clean, noise = _aggregate(rows), _aggregate(noisy)
    return {"overall": clean, "by_type": {t: _aggregate([r for r in rows if r["type"] == t])
                                          for t in sorted({r["type"] for r in rows})},
            "by_tag": by_tag, "noise": {**noise, "kind": "2 swapped-letter typos per question",
                                        "delta": {k: (noise[k] or 0) - (clean[k] or 0)
                                                  for k in ("recall@3", "recall@5", "mrr", "ndcg@5")}},
            "unanswerable_top1_mean": m.mean(absent_top1), "unanswerable_top1_max":
            max(absent_top1, default=None), "per_question": rows}


# ------------------------------------------------------------------ end-to-end level
def judge(http: httpx.Client, cfg: Config, question: str, evidence: list[dict[str, Any]],
          answer: str) -> bool | None:
    """LLM-as-judge for faithfulness: is every claim in the answer supported by the evidence?"""
    if not (cfg.llm_base and cfg.llm_model and cfg.llm_key):
        return None
    context = "\n\n".join(f"[{i}] {e['text']}" for i, e in enumerate(evidence, 1))
    prompt = (f"Question: {question}\n\nEvidence:\n{context}\n\nAnswer:\n{answer}\n\n"
              "Is every factual claim in the answer supported by the evidence above? Reply with "
              "SUPPORTED or UNSUPPORTED on the first line, then one short reason.")
    body = {"model": cfg.llm_model, "temperature": 0,
            "messages": [{"role": "system", "content": "You are a strict grader of faithfulness."},
                         {"role": "user", "content": prompt}]}
    for attempt in range(4):
        r = http.post(f"{cfg.llm_base}/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {cfg.llm_key}"})
        if r.status_code in (429, 500, 502, 503):
            time.sleep(min(20.0, float(r.headers.get("retry-after", 2 ** attempt * 2))))
            continue
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip().upper()
        return not text.startswith("UNSUPPORTED") and text.startswith("SUPPORTED")
    return None


def run_e2e(http: httpx.Client, cfg: Config, questions: list[dict[str, Any]],
            run_no: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(questions):
        if i and cfg.delay:
            time.sleep(cfg.delay)
        trace_id = f"eval-{cfg.run_id}-r{run_no}-{q['id']}"
        started = time.perf_counter()
        r = http.post(f"{cfg.api}/api/ask", headers={"X-Request-ID": trace_id},
                      json={"question": q["question"], "no_cache": True, "include_evidence": True})
        seconds = time.perf_counter() - started
        r.raise_for_status()
        a = r.json()
        retrieved = {(c["source"], c["section"]) for c in a["retrieved"]}
        cites = a.get("citations") or []
        valid = sum(1 for c in cites if (c["source"], c["section"]) in retrieved)
        answered = bool(a["answered_from_context"])
        verdict = judge(http, cfg, q["question"], a.get("evidence") or [], a["answer"]) \
            if answered and a.get("evidence") else None
        text = a["answer"].lower()
        rows.append({
            "id": q["id"], "type": q["type"], "trace_id": a.get("request_id", trace_id),
            "answered": answered, "fallback": bool(a.get("fallback")), "seconds": round(seconds, 3),
            "citations": len(cites), "citations_valid": valid, "faithful": verdict,
            "contains_expected": (all(e.lower() in text for e in q["expected"])
                                  if q["expected"] and answered else None)})
    unans = [r for r in rows if r["type"] == "unanswerable"]
    ans = [r for r in rows if r["type"] != "unanswerable"]
    cites = sum(r["citations"] for r in rows)
    judged = [r for r in rows if r["faithful"] is not None]
    labels = json.loads(cfg.labels.read_text()) if cfg.labels.exists() else {}
    both = [r for r in judged if r["id"] in labels]
    agree = [bool(r["faithful"]) == bool(labels[r["id"]]["supported"]) for r in both]
    seconds = [r["seconds"] for r in rows]
    expected = [r["contains_expected"] for r in ans if r["contains_expected"] is not None]
    return {
        "questions": len(rows),
        "citation_validity": sum(r["citations_valid"] for r in rows) / cites if cites else None,
        "citations_checked": cites,
        "abstention_correctness": (sum(not r["answered"] for r in unans) / len(unans)
                                   if unans else None),
        "false_abstention_rate": (sum(not r["answered"] for r in ans) / len(ans) if ans else None),
        "faithfulness": (sum(bool(r["faithful"]) for r in judged) / len(judged)
                         if judged else None),
        "faithfulness_judged": len(judged),
        "judge_agreement_with_human": sum(agree) / len(agree) if agree else None,
        "human_labels_used": len(agree),
        "answer_contains_expected": sum(expected) / len(expected) if expected else None,
        "fallbacks": sum(r["fallback"] for r in rows),
        "latency_p50_s": m.percentile(seconds, 50), "latency_p95_s": m.percentile(seconds, 95),
        "per_question": rows}


# ------------------------------------------------------------------ orchestration
def flatten(result: dict[str, Any]) -> dict[str, float]:
    flat: dict[str, float] = {}
    mod = result.get("module") or {}
    for k in ("paraphrase_mean", "unrelated_mean", "gap", "ranked_correctly", "ms_per_chunk",
              "determinism_max_abs_diff"):
        if isinstance(mod.get(k), (int, float)):
            flat[f"module.{k}"] = float(mod[k])
    comp = result.get("component") or {}
    for k, v in (comp.get("overall") or {}).items():
        if isinstance(v, (int, float)) and k != "questions":
            flat[f"component.{k}"] = float(v)
    for k, v in ((comp.get("noise") or {}).get("delta") or {}).items():
        flat[f"component.noise_delta.{k}"] = float(v)
    e2e = result.get("e2e") or {}
    for k in ("citation_validity", "abstention_correctness", "false_abstention_rate",
              "faithfulness", "answer_contains_expected", "latency_p50_s", "latency_p95_s"):
        if isinstance(e2e.get(k), (int, float)):
            flat[f"e2e.{k}"] = float(e2e[k])
    return flat


def run_once(http: httpx.Client, cfg: Config, questions: list[dict[str, Any]], run_no: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    todo = active(questions, cfg)
    if "module" in cfg.levels:
        result["module"] = run_module(http, cfg)
    if "component" in cfg.levels:
        result["component"] = run_component(http, cfg, todo)
    if "e2e" in cfg.levels:
        result["e2e"] = run_e2e(http, cfg, todo, run_no)
    result["flat"] = flatten(result)
    return result


def fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{100 * v:.1f}%" if pct else f"{v:.3f}"


def summary_table(report: dict[str, Any]) -> str:
    s, v = report["summary"], report["variation"]
    first = report["runs"][0]
    lines = [f"# RAGOps test suite {report['run_id']}", "",
             f"golden questions: {report['golden']['active']} of {report['golden']['total']} "
             f"(Batch B included: {report['config']['batch_b']}) · runs: {report['config']['repeat']} "
             f"· seed {report['config']['seed']} · page tolerance ±{report['config']['tolerance']}", "",
             "| Level | Metric | Value | Spread between runs |", "| --- | --- | ---: | ---: |"]
    def row(level: str, label: str, key: str, pct: bool = False) -> None:
        if key in s:
            lines.append(f"| {level} | {label} | {fmt(s[key], pct)} | {fmt(v.get(key))} |")
    row("module", "paraphrase mean cosine", "module.paraphrase_mean")
    row("module", "unrelated mean cosine", "module.unrelated_mean")
    row("module", "gap (paraphrase minus unrelated)", "module.gap")
    row("module", "paraphrase beats unrelated (pairs)", "module.ranked_correctly", True)
    row("module", "embedding time per chunk (ms)", "module.ms_per_chunk")
    row("module", "determinism: largest difference", "module.determinism_max_abs_diff")
    for key, label in (("recall@3", "recall@3"), ("recall@5", "recall@5"), ("mrr", "MRR"),
                       ("ndcg@5", "nDCG@5")):
        row("component", label, f"component.{key}")
        row("component", f"{label} change with typos", f"component.noise_delta.{key}")
    row("e2e", "faithfulness (LLM judge)", "e2e.faithfulness", True)
    row("e2e", "abstention correctness", "e2e.abstention_correctness", True)
    row("e2e", "citation validity", "e2e.citation_validity", True)
    row("e2e", "false abstentions on answerable", "e2e.false_abstention_rate", True)
    row("e2e", "answer contains expected text", "e2e.answer_contains_expected", True)
    row("e2e", "latency p50 (s)", "e2e.latency_p50_s")
    row("e2e", "latency p95 (s)", "e2e.latency_p95_s")
    comp = first.get("component") or {}
    if comp.get("by_tag"):
        lines += ["", "recall@5 by question kind:", "", "| Kind | Questions | recall@5 | MRR |",
                  "| --- | ---: | ---: | ---: |"]
        for tag, agg in comp["by_tag"].items():
            lines.append(f"| {tag} | {agg['questions']} | {fmt(agg['recall@5'])} | {fmt(agg['mrr'])} |")
    return "\n".join(lines) + "\n"


def run_suite(cfg: Config, http: httpx.Client | None = None) -> dict[str, Any]:
    own = http is None
    http = http or httpx.Client(timeout=120.0, headers={"Host": cfg.host} if cfg.host else {})
    try:
        questions = load_golden(cfg.golden)
        runs = [run_once(http, cfg, questions, n + 1) for n in range(cfg.repeat)]
    finally:
        if own:
            http.close()
    keys = sorted({k for r in runs for k in r["flat"]})
    summary = {k: m.mean([r["flat"][k] for r in runs if k in r["flat"]]) for k in keys}
    variation = {k: m.spread([r["flat"][k] for r in runs if k in r["flat"]]) for k in keys}
    return {"run_id": cfg.run_id, "started_at": datetime.now(timezone.utc).isoformat(),
            "config": {"api": cfg.api, "embed_model": cfg.model, "llm_model": cfg.llm_model,
                       "judge": bool(cfg.llm_key), "seed": cfg.seed, "repeat": cfg.repeat,
                       "tolerance": cfg.tolerance, "batch_b": cfg.batch_b,
                       "levels": list(cfg.levels), "delay": cfg.delay},
            "golden": {"total": len(questions), "active": len(active(questions, cfg))},
            "runs": runs, "summary": summary, "variation": variation}


def write_results(report: dict[str, Any], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    stem = f"suite-{report['run_id']}"
    paths = [out / f"{stem}.json", out / f"{stem}.md"]
    paths[0].write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    paths[1].write_text(summary_table(report), encoding="utf-8")
    return paths


def parse(argv: list[str] | None = None) -> Config:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("API_URL", "http://api:8000"))
    ap.add_argument("--host", default="", help="Host header, when going through the Ingress")
    ap.add_argument("--ollama", default=os.environ.get("OLLAMA_URL", ""))
    ap.add_argument("--out", type=Path, default=HERE / "results")
    ap.add_argument("--levels", default=",".join(LEVELS))
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between model calls")
    ap.add_argument("--tolerance", type=int, default=1, help="page tolerance for relevance")
    ap.add_argument("--batch-b", action="store_true", help="include the Batch B questions")
    a = ap.parse_args(argv)
    return Config(api=a.api.rstrip("/"), host=a.host, ollama=a.ollama.rstrip("/"),
                  model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
                  llm_base=os.environ.get("HOSTED_BASE_URL", "").rstrip("/"),
                  llm_model=os.environ.get("LLM_MODEL", ""), llm_key=os.environ.get("LLM_API_KEY", ""),
                  out=a.out, levels=tuple(x for x in a.levels.split(",") if x in LEVELS),
                  repeat=max(1, a.repeat), seed=a.seed, delay=a.delay, tolerance=a.tolerance,
                  batch_b=a.batch_b)


def main(argv: list[str] | None = None) -> int:
    cfg = parse(argv)
    report = run_suite(cfg)
    paths = write_results(report, cfg.out)
    print(summary_table(report))
    print("wrote " + ", ".join(str(p) for p in paths), flush=True)
    return 0

