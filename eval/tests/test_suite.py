"""Tests for the RAGOps part B suite, against a mocked API, embedding service and judge."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import httpx
import pytest

from eval import golden_lint
from eval.suite import metrics as m
from eval.suite import runner

HERE = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- metrics
def chunk(source: str, page: int) -> dict[str, Any]:
    return {"source": source, "page": page, "section": "s", "chunk_id": f"{source}-{page}"}


def test_recall_mrr_ndcg_on_a_known_ranking() -> None:
    relevant = [{"doc": "a.pdf", "pages": [10]}, {"doc": "b.pdf", "pages": [50]}]
    ranked = [chunk("x.pdf", 1), chunk("a.pdf", 10), chunk("x.pdf", 2), chunk("b.pdf", 51),
              chunk("x.pdf", 3)]
    s = m.retrieval_scores(ranked, relevant, tolerance=1)
    assert s["recall@3"] == 0.5 and s["recall@5"] == 1.0       # b.pdf p51 is within +/-1 of 50
    assert s["mrr"] == pytest.approx(0.5)                      # first hit at rank 2
    dcg = 1 / math.log2(3) + 1 / math.log2(5)                  # hits at ranks 2 and 4
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert s["ndcg@5"] == pytest.approx(dcg / ideal)


def test_a_miss_scores_zero_and_tolerance_zero_is_strict() -> None:
    relevant = [{"doc": "a.pdf", "pages": [10]}]
    assert m.retrieval_scores([chunk("a.pdf", 9)], relevant, tolerance=0)["recall@5"] == 0.0
    assert m.retrieval_scores([chunk("a.pdf", 9)], relevant, tolerance=1)["recall@5"] == 1.0
    assert m.retrieval_scores([], relevant)["mrr"] == 0.0


def test_percentile_cosine_and_typos_are_deterministic() -> None:
    assert m.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == 10
    assert m.percentile([1, 2, 3, 4], 50) == 2
    assert m.cosine([1, 0], [1, 0]) == pytest.approx(1.0) and m.cosine([1, 0], [0, 1]) == 0.0
    a = m.typo("What does the Dodge action do until the start", random.Random(1))
    b = m.typo("What does the Dodge action do until the start", random.Random(1))
    assert a == b and a != "What does the Dodge action do until the start"
    assert sorted(a.replace(" ", "")) == sorted("What does the Dodge action do until the start".replace(" ", ""))


# ---------------------------------------------------------------- the golden set
def test_the_golden_set_is_well_formed_and_lint_reports_only_the_human_work_left() -> None:
    counts, problems = golden_lint.lint(HERE / "golden.jsonl")
    assert counts["questions"] >= 25 and counts["answerable"] >= 15
    assert counts["unanswerable"] >= 5 and counts["hard"] >= 5
    assert [p for p in problems if not p.startswith(("human:", "synthetic_reviewed:"))] == []


def test_the_embedding_pairs_meet_the_minimums() -> None:
    pairs = json.loads((HERE / "embedding_pairs.json").read_text())
    assert len(pairs["paraphrase"]) >= 15 and len(pairs["unrelated"]) >= 15


# ---------------------------------------------------------------- the runner, on a mock cluster
def make_cluster(break_citation: bool = False, answer_everything: bool = False) -> httpx.Client:
    golden = {q["question"]: q for q in runner.load_golden(HERE / "golden.jsonl")}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == "/api/embed":
            vecs = []
            for text in body["input"]:
                v = [0.0] * 8
                for w in text.replace("search_query: ", "").replace("search_document: ", "").split():
                    v[sum(map(ord, w)) % 8] += 1.0
                vecs.append(v)
            return httpx.Response(200, json={"embeddings": vecs})
        if path in ("/api/retrieve", "/api/ask"):
            q = golden.get(body["question"]) or next(
                (g for g in golden.values() if g["question"][:20] == body["question"][:20]),
                {"relevant": [], "type": "unanswerable", "expected": []})
            rel = q["relevant"]
            hits = [{"chunk_id": "c", "source": r["doc"], "section": "S", "page": r["pages"][0],
                     "score": 0.8} for r in rel]
            noise = [{"chunk_id": "n", "source": "other.pdf", "section": "S", "page": 1, "score": 0.5}]
            retrieved = (hits + noise) if rel else noise
            if path == "/api/retrieve":
                return httpx.Response(200, json={"retrieved": retrieved})
            answered = bool(rel) or answer_everything
            cite = ({"source": "bogus.pdf", "section": "X", "page": 1} if break_citation else
                    {"source": retrieved[0]["source"], "section": "S", "page": retrieved[0]["page"]})
            return httpx.Response(200, json={
                "request_id": request.headers["x-request-id"], "answered_from_context": answered,
                "answer": " ".join(q["expected"]) or "The corpus does not cover that.",
                "citations": [cite] if answered else [], "retrieved": retrieved, "fallback": False,
                "evidence": [{"chunk_id": "c", "source": "s", "section": "S", "page": 1,
                              "text": "evidence"}] if answered else None})
        if path.endswith("/chat/completions"):
            calls["n"] += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "SUPPORTED\nok"}}]})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def config(tmp_path: Path, **kw: Any) -> runner.Config:
    base = dict(api="http://api", ollama="http://ollama", out=tmp_path, delay=0.0, repeat=2,
                llm_base="http://llm", llm_model="judge", llm_key="k", run_id="T1")
    base.update(kw)
    return runner.Config(**base)  # type: ignore[arg-type]


def test_the_suite_runs_all_three_levels_and_writes_results(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    report = runner.run_suite(cfg, make_cluster())
    s = report["summary"]
    assert report["golden"] == {"total": 39, "active": 35}            # Batch B waits for --batch-b
    assert s["component.recall@5"] == pytest.approx(1.0) and s["component.mrr"] == pytest.approx(1.0)
    assert s["e2e.abstention_correctness"] == 1.0 and s["e2e.citation_validity"] == 1.0
    assert s["e2e.faithfulness"] == 1.0 and s["e2e.latency_p95_s"] >= s["e2e.latency_p50_s"]
    assert s["module.determinism_max_abs_diff"] == 0.0 and "module.gap" in s
    assert report["variation"]["component.recall@5"] == 0.0           # two identical runs
    first = report["runs"][0]["component"]
    assert first["noise"]["questions"] == first["overall"]["questions"] > 0
    paths = runner.write_results(report, tmp_path)
    assert [p.suffix for p in paths] == [".json", ".md"] and all(p.exists() for p in paths)
    table = paths[1].read_text()
    assert "| module |" in table and "| component |" in table and "| e2e |" in table


def test_batch_b_questions_are_included_only_when_asked(tmp_path: Path) -> None:
    report = runner.run_suite(config(tmp_path, batch_b=True, levels=("component",)), make_cluster())
    assert report["golden"]["active"] == 39
    kinds = report["runs"][0]["component"]["by_tag"]
    assert "batch-b" in kinds and kinds["batch-b"]["questions"] == 4


def test_a_fabricated_citation_and_a_wrongly_answered_abstention_are_measured(tmp_path: Path) -> None:
    report = runner.run_suite(config(tmp_path, levels=("e2e",), repeat=1),
                              make_cluster(break_citation=True, answer_everything=True))
    s = report["summary"]
    assert s["e2e.citation_validity"] == 0.0                          # none matches a retrieved chunk
    assert s["e2e.abstention_correctness"] == 0.0                     # every unanswerable was answered


def test_without_a_judge_faithfulness_is_absent_not_invented(tmp_path: Path) -> None:
    report = runner.run_suite(config(tmp_path, llm_key="", levels=("e2e",), repeat=1), make_cluster())
    assert "e2e.faithfulness" not in report["summary"]
    assert report["config"]["judge"] is False


def test_human_labels_give_a_judge_agreement_figure(tmp_path: Path) -> None:
    labels = tmp_path / "labels.json"
    ids = [q["id"] for q in runner.load_golden(HERE / "golden.jsonl") if q["type"] == "answerable"][:4]
    labels.write_text(json.dumps({i: {"supported": i != ids[0]} for i in ids}))
    cfg = config(tmp_path, levels=("e2e",), repeat=1, labels=labels)
    e2e = runner.run_suite(cfg, make_cluster())["runs"][0]["e2e"]
    assert e2e["human_labels_used"] == 4
    assert e2e["judge_agreement_with_human"] == pytest.approx(0.75)   # judge said SUPPORTED to all


def test_module_level_is_skipped_without_an_embedding_url(tmp_path: Path) -> None:
    report = runner.run_suite(config(tmp_path, ollama="", levels=("module",), repeat=1), make_cluster())
    assert "skipped" in report["runs"][0]["module"] and report["summary"] == {}
