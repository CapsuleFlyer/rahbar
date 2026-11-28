from __future__ import annotations

import pytest

from eval.live_coverage import build_report, cosine, render_markdown


def test_cosine_similarity_handles_identical_orthogonal_and_zero_vectors() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_live_queries_match_the_nearest_golden_question_and_group_misses() -> None:
    live = [
        {"id": "e01", "question": "Hide action?", "scope": "in", "topic": "combat"},
        {"id": "e02", "question": "Capital of France?", "scope": "out", "topic": "general"},
        {"id": "e03", "question": "Exhaustion?", "scope": "in", "topic": "conditions"},
    ]
    golden = [
        {"id": "g01", "question": "How does Hide work?"},
        {"id": "g02", "question": "How does Exhaustion work?"},
    ]
    report = build_report(
        live, golden,
        [[1.0, 0.0], [0.6, 0.8], [0.0, 0.0]],
        [[1.0, 0.0], [0.0, 1.0]],
        0.85, "test-model",
    )
    assert report["rows"][0]["best_golden_id"] == "g01"
    assert report["rows"][1]["best_golden_id"] == "g02"
    assert report["in_domain_covered"] == 1
    assert report["in_domain_coverage"] == pytest.approx(0.5)
    assert report["out_domain_above_threshold"] == 0
    assert report["uncovered_topics"] == {"conditions": ["e03"]}
    markdown = render_markdown(report)
    assert "Uncovered in-domain queries by topic" in markdown
    assert "e03" in markdown


def test_semantic_coverage_includes_all_golden_questions() -> None:
    live = [{"id": "e01", "question": "Question", "scope": "in", "topic": "test"}]
    golden = [{"id": "g01", "question": "Question"}]
    report = build_report(live, golden, [[1.0, 0.0]], [[1.0, 0.0]], 0.85, "test-model")
    assert report["golden_questions"] == 1
    assert report["rows"][0]["covered"] is True
