from eval.coverage_repair import build_plan, normalize, render_markdown


def test_normalize_ignores_punctuation_and_case():
    assert normalize("Hide Action: What does it do?") == "hide action what does it do"


def test_plan_groups_uncovered_and_flags_exact_duplicates():
    report = {
        "threshold": 0.85, "minimum_in_domain_coverage": 0.85,
        "in_domain_coverage": 0.5, "in_domain_covered": 1,
        "counts": {"in": 2},
        "rows": [
            {"id": "e01", "scope": "in", "covered": False, "question": "What does Hide do?",
             "topic": "version", "best_golden_id": "g01",
             "best_golden_question": "How does Hide work?", "similarity": 0.7},
            {"id": "e02", "scope": "in", "covered": True, "question": "Already covered?",
             "topic": "combat", "best_golden_id": "g02",
             "best_golden_question": "Covered?", "similarity": 0.9},
        ],
    }
    queries = {"queries": [
        {"id": "e01", "question": "What does Hide do?", "scope": "in",
         "source": "rules.pdf", "section": "Hide", "topic": "version"},
        {"id": "e02", "question": "Already covered?", "scope": "in",
         "source": "rules.pdf", "section": "Dodge", "topic": "combat"},
    ]}
    golden = [{"id": "g01", "question": "What does Hide do?"}]
    plan = build_plan(report, queries, golden)

    assert plan["candidate_count"] == 1
    assert plan["uncovered_topics"] == {"version": ["e01"]}
    assert plan["candidates"][0]["exact_duplicate"] is True
    assert plan["candidates"][0]["source"] == "rules.pdf"
    assert plan["candidates"][0]["relevant"] == []
    assert "verify the page number" in render_markdown(plan)
