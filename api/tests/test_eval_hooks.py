"""The evaluation hooks of RAGOps part B: no_cache, evidence text and the retrieval-only route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.schemas import AskResponse
from app.services.answer import answer_question
from app.services.cache import SemanticCache
from conftest import FakeRedis, FakeRetriever, ScriptedProvider, good_answer, make_passage


def test_no_cache_skips_lookup_and_store(settings: Settings) -> None:
    cache = SemanticCache(FakeRedis(), 0.92, 60, generation_id=lambda: "g")
    ret = FakeRetriever([make_passage()], vector=[1.0, 0.0])
    q = "How many hours of attendance are required?"
    first = answer_question(q, ret, ScriptedProvider(good_answer()), settings, cache, no_cache=True)
    again = answer_question(q, ret, ScriptedProvider(good_answer()), settings, cache)
    assert first.cached is False and again.cached is False       # nothing was stored by the first
    third = answer_question(q, ret, ScriptedProvider(good_answer()), settings, cache, no_cache=True)
    assert third.cached is False                                  # and the stored one is not read


def test_evidence_text_is_returned_only_when_asked(settings: Settings) -> None:
    ret = FakeRetriever([make_passage(text="Attendance of 80 percent is required.")])
    q = "How many hours of attendance are required?"
    plain = answer_question(q, ret, ScriptedProvider(good_answer()), settings)
    with_ev = answer_question(q, ret, ScriptedProvider(good_answer()), settings,
                              include_evidence=True)
    assert plain.evidence is None
    assert with_ev.evidence and with_ev.evidence[0].text == "Attendance of 80 percent is required."


def test_retrieve_route_returns_chunks_without_a_model_call(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RETRIEVER", "stub")
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    from app.main import app

    with TestClient(app) as client:
        r = client.post("/api/retrieve", json={"question": "What does the stub say?", "k": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["k"] == 2 and body["include_superseded"] is False
        assert body["retrieved"] and {"chunk_id", "source", "section", "score"} <= set(
            body["retrieved"][0])
        old = client.post("/api/retrieve", json={"question": "What did the older 2014 rules say?"})
        assert old.json()["include_superseded"] is True
        assert client.post("/api/retrieve", json={"question": "hi"}).status_code == 422
        ask = AskResponse(**client.post("/api/ask", json={
            "question": "What does the stub say?", "include_evidence": True}).json())
        assert ask.evidence is not None
