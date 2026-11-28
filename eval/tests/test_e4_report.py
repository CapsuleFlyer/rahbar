from __future__ import annotations

import pytest

from eval.e4_report import compare_e4, render_markdown


def report(covered: int) -> dict:
    return {
        "threshold": 0.85,
        "live_queries": 40,
        "counts": {"in": 28, "out": 12},
        "in_domain_covered": covered,
        "gate_passed": covered / 28 >= 0.85,
    }


def golden(count: int, start: int = 1) -> list[dict]:
    return [{"id": f"g{x:02}", "question": f"Question {x}"} for x in range(start, start + count)]


def test_e4_requires_six_new_questions_and_measured_coverage_increase() -> None:
    result = compare_e4(report(14), report(16), golden(45), golden(51))
    assert result["added_question_count"] == 6
    assert result["coverage_increase_queries"] == 2
    assert result["coverage_increase_percentage_points"] == pytest.approx(100 * 2 / 28)
    assert result["e4_demonstration_passed"] is True
    assert result["e2_coverage_gate_passed_after_e4"] is False
    assert "E2 85% coverage gate after E4: FAIL" in render_markdown(result)


def test_e4_fails_when_coverage_does_not_increase() -> None:
    result = compare_e4(report(14), report(14), golden(45), golden(51))
    assert result["e4_six_questions_requirement_met"] is True
    assert result["coverage_increased"] is False
    assert result["e4_demonstration_passed"] is False


def test_e4_rejects_removed_baseline_questions() -> None:
    with pytest.raises(ValueError, match="cannot remove"):
        compare_e4(report(14), report(16), golden(45), golden(50, 2))
