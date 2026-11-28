"""Tests for the Part C baseline-versus-candidate release gate."""

from __future__ import annotations

from typing import Any

from eval.experiment_gate import evaluate


def report(summary: dict[str, float], top_k: int) -> dict[str, Any]:
    return {
        "config": {
            "embed_model": "nomic-embed-text",
            "llm_model": "test-model",
            "batch_b": False,
            "levels": ["module", "component", "e2e"],
            "top_k": top_k,
        },
        "golden": {"active": 35},
        "summary": summary,
    }


def test_gate_passes_candidate_with_small_changes() -> None:
    metrics = {
        "module.gap": 0.28,
        "module.ranked_correctly": 1.0,
        "module.determinism_max_abs_diff": 0.0,
        "component.recall@5": 0.91,
        "component.mrr": 0.78,
        "component.ndcg@5": 0.97,
        "e2e.faithfulness": 0.95,
        "e2e.citation_validity": 1.0,
        "e2e.abstention_correctness": 1.0,
        "e2e.false_abstention_rate": 0.24,
        "e2e.answer_contains_expected": 0.52,
        "e2e.latency_p95_s": 16.0,
    }
    baseline = report(metrics, 5)
    candidate = report(dict(metrics), 8)
    thresholds = {
        "required_levels": ["module", "component", "e2e"],
        "rules": {
            "module.gap": {"min_delta": -0.01},
            "module.ranked_correctly": {"min": 0.95},
            "module.determinism_max_abs_diff": {"max": 0.001},
            "component.recall@5": {"min_delta": -0.03},
            "component.mrr": {"min_delta": -0.03},
            "component.ndcg@5": {"min_delta": -0.03},
            "e2e.faithfulness": {"min_delta": -0.03},
            "e2e.citation_validity": {"min": 0.98},
            "e2e.abstention_correctness": {"min": 0.95},
            "e2e.false_abstention_rate": {"max_delta": 0.05},
            "e2e.answer_contains_expected": {"min_delta": -0.05},
            "e2e.latency_p95_s": {"max_ratio": 1.25},
        },
    }
    passed, failures = evaluate(baseline, candidate, thresholds)
    assert passed and failures == []


def test_gate_rejects_retrieval_regression() -> None:
    baseline = report({"component.recall@5": 0.92}, 5)
    candidate = report({"component.recall@5": 0.80}, 1)
    thresholds = {"required_levels": [], "rules": {"component.recall@5": {"min_delta": -0.03}}}
    passed, failures = evaluate(baseline, candidate, thresholds)
    assert not passed
    assert any("component.recall@5" in failure for failure in failures)


def test_gate_rejects_different_question_sets() -> None:
    baseline = report({"component.recall@5": 0.92}, 5)
    candidate = report({"component.recall@5": 0.92}, 8)
    candidate["golden"]["active"] = 39
    passed, failures = evaluate(
        baseline,
        candidate,
        {"required_levels": [], "rules": {"component.recall@5": {"min_delta": -0.03}}},
    )
    assert not passed
    assert any("different active golden" in failure for failure in failures)
