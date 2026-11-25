"""Turns a question into an AskResponse: the query pipeline of section 3.2.

 1 receive/validate (the route)  2 cache check  3 embed  4 retrieve (+ superseded filter)
 5 augment  6 generate  7 validate (+ retry, fallback)  8 store (+ cache)

Every request also writes ONE trace record (RAGOps D1, see trace.py). It is built as the
request goes and emitted on every exit, including failures and cache hits, so that any
answer can be explained afterwards with scripts/trace_show.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from .. import guardrails
from ..config import Settings
from ..logjson import request_id_var
from ..providers.llm.base import LLMProvider, Usage
from ..retrieval.base import Retriever
from ..routes import metrics
from ..schemas import Answer, AskResponse, Passage, RetrievedRef
from ..trace import TraceWriter
from . import cache as cache_mod
from .grounding import (
    abstention_answer,
    apply_floor,
    fallback_answer,
    generate_with_validation,
)
from .intent import is_followup, wants_older_version
from .prompt import build_messages

log = logging.getLogger("rahbar.answer")


def _response(
    answer: Answer, passages: list[Passage], provider_name: str, cached: bool = False
) -> AskResponse:
    return AskResponse(
        request_id=request_id_var.get(),
        answer=answer.answer,
        citations=answer.citations,
        answered_from_context=answer.answered_from_context,
        confidence=answer.confidence,
        retrieved=[
            RetrievedRef(chunk_id=p.chunk_id, source=p.source, section=p.section,
                         page=p.page, score=p.score)
            for p in passages
        ],
        provider=provider_name,
        cached=cached,
    )


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _ref(p: Passage) -> dict[str, Any]:
    return {"chunk_id": p.chunk_id, "doc_id": p.source, "doc_version": p.doc_version,
            "superseded": p.superseded, "section": p.section, "page": p.page,
            "score": round(p.score, 4)}


def _begin_trace(question: str, retriever: Retriever, settings: Settings, followup: bool,
                 include_old: bool) -> dict[str, Any]:
    return {
        "trace_id": request_id_var.get(),
        "query": question,
        "rewritten_query": None,            # this pipeline does not rewrite queries
        "followup": followup,
        "retriever": retriever.name,
        "embedding": {"model": settings.embed_model, "dimension": None},
        "collection": {"name": settings.collection},
        "filters": {"where": None if include_old else {"superseded": False},
                    "include_superseded": include_old},
        "params": {"top_k": settings.top_k, "relevance_floor": settings.relevance_floor,
                   "cache_threshold": settings.cache_threshold},
        "cache": {"result": "skipped"},
        "retrieved": [],
        "rerank": {"applied": False, "order": []},
        "guardrails": [],
        "prompt": None,
        "generation": None,
        "response": None,
        "latency_ms": {},
        "outcome": None,
    }


def _note_index(tr: dict[str, Any], retriever: Retriever, vector: list[float] | None) -> None:
    """Which index and embedding model served this request (needed for the F3 rollback proof)."""
    try:
        info = retriever.index_info()
    except Exception:  # the trace must never be the reason a question fails
        info = {}
    tr["collection"].update(index_id=info.get("index_id"), built_at=info.get("built_at"))
    tr["embedding"].update(dimension=len(vector) if vector else info.get("dimension"),
                           index_embed_model=info.get("embed_model"))


def _response_record(answer: Answer, fallback: str | None = None,
                     dropped: int = 0) -> dict[str, Any]:
    return {"answer": answer.answer,
            "citations": [c.model_dump() for c in answer.citations],
            "answered_from_context": answer.answered_from_context,
            "confidence": answer.confidence, "reasoning": answer.reasoning,
            "fallback": fallback, "citations_dropped": dropped}


def answer_question(
    question: str,
    retriever: Retriever,
    provider: LLMProvider,
    settings: Settings,
    cache: cache_mod.SemanticCache | None = None,
    trace: TraceWriter | None = None,
) -> AskResponse:
    began = time.perf_counter()
    followup = is_followup(question)
    include_old = wants_older_version(question)
    fields: dict[str, Any] = {
        "retriever": retriever.name, "provider": provider.name, "top_k": settings.top_k,
        "followup": followup, "include_superseded": include_old, "cached": False,
        "abstention": False, "fallback": None, "chunk_ids": [], "scores": [],
        "answered_from_context": False,
    }
    tr = _begin_trace(question, retriever, settings, followup, include_old)

    def done(response: AskResponse, outcome: str) -> AskResponse:
        """The single exit: stamp the outcome and total time, write the trace, return."""
        tr["outcome"] = outcome
        tr["latency_ms"]["total"] = _ms(began)
        if trace is not None:
            try:
                trace.write(tr)
            except Exception:
                log.warning("trace write failed", exc_info=True)
        return response

    # D4: the retrieval rail looks at the question too. It records; the delimiting defence acts.
    hits = guardrails.scan(question)
    if hits:
        metrics.INJECTION_FLAGGED.labels(target="question").inc()
        tr["guardrails"].append({
            "rail": "injection_scan", "target": "question", "patterns": hits,
            "action": "flagged",
            "note": "the question stays delimited as data and the answer is schema-constrained"})

    # 3. embed once; the same vector serves the cache lookup and the retrieval
    started = time.perf_counter()
    try:
        vector = retriever.embed_query(question)
    except Exception as exc:
        metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
        metrics.STAGE_LATENCY.labels(stage="embed").observe(time.perf_counter() - started)
        tr["latency_ms"]["embed"] = _ms(started)
        tr["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return done(_failed("embedding_error", exc, fields, provider.name),
                    "fallback:embedding_error")
    metrics.STAGE_LATENCY.labels(stage="embed").observe(time.perf_counter() - started)
    tr["latency_ms"]["embed"] = _ms(started)
    _note_index(tr, retriever, vector)

    # 2. cache check (skipped for follow-ups and when there is no vector)
    if cache is not None and vector is not None and not followup:
        cache_started = time.perf_counter()
        hit = cache.lookup(vector, include_old)
        metrics.STAGE_LATENCY.labels(stage="cache").observe(time.perf_counter() - cache_started)
        tr["latency_ms"]["cache"] = _ms(cache_started)
        metrics.CACHE_REQUESTS.labels(result="hit" if hit else "miss").inc()
        tr["cache"] = {"result": "hit" if hit else "miss"}
        if hit:
            response = AskResponse(**{**hit, "request_id": request_id_var.get(), "cached": True})
            fields.update(cached=True, answered_from_context=response.answered_from_context,
                          chunk_ids=[r.chunk_id for r in response.retrieved])
            log.info("answered", extra=fields)
            tr["from_cache"] = True
            tr["retrieved"] = [{"chunk_id": r.chunk_id, "doc_id": r.source, "doc_version": None,
                                "superseded": None, "section": r.section, "page": r.page,
                                "score": round(r.score, 4)} for r in response.retrieved]
            tr["response"] = {"answer": response.answer,
                              "citations": [c.model_dump() for c in response.citations],
                              "answered_from_context": response.answered_from_context,
                              "confidence": response.confidence}
            return done(response, "cache_hit")
    else:
        tr["cache"] = {"result": "skipped",
                       "reason": "followup" if followup else "cache off or no embedding"}

    # 4. retrieve (superseded documents filtered unless the user asked about an old version)
    retrieve_started = time.perf_counter()
    try:
        retrieved = retriever.retrieve(question, k=settings.top_k, vector=vector,
                                       include_superseded=include_old)
    except Exception as exc:
        metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
        tr["latency_ms"]["retrieve"] = _ms(retrieve_started)
        tr["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return done(_failed("retrieval_error", exc, fields, provider.name),
                    "fallback:retrieval_error")
    metrics.RETRIEVAL_LATENCY.observe(time.perf_counter() - started)
    metrics.STAGE_LATENCY.labels(stage="retrieve").observe(time.perf_counter() - retrieve_started)
    tr["latency_ms"]["retrieve"] = _ms(retrieve_started)
    fields.update(chunk_ids=[p.chunk_id for p in retrieved],
                  scores=[round(p.score, 4) for p in retrieved])
    tr["retrieved"] = [_ref(p) for p in retrieved]
    if retrieved:
        metrics.TOP1_SCORE.observe(retrieved[0].score)

    # relevance floor: abstain honestly, without spending an LLM call
    evidence = apply_floor(retrieved, settings.relevance_floor)
    in_prompt = {p.chunk_id for p in evidence}
    tr["rerank"] = {"applied": False, "order": [p.chunk_id for p in evidence]}

    # D4: scan retrieved text for injected instructions and record what the rail saw
    for p in retrieved:
        found = guardrails.scan(p.text)
        if found:
            metrics.INJECTION_FLAGGED.labels(target="chunk").inc()
            tr["guardrails"].append({
                "rail": "injection_scan", "target": "chunk", "chunk_id": p.chunk_id,
                "doc_id": p.source, "doc_version": p.doc_version, "patterns": found,
                "in_prompt": p.chunk_id in in_prompt, "action": "flagged",
                "note": "evidence is delimited, markup-escaped and answered under a fixed schema"})

    if not evidence:
        metrics.ABSTENTIONS.inc()
        fields.update(abstention=True)
        log.info("answered", extra=fields)
        answer = abstention_answer()
        tr["response"] = _response_record(answer)
        return done(_response(answer, retrieved, provider.name), "abstained:floor")

    # 5-7. augment, generate, validate (one retry, then the canned fallback)
    messages = build_messages(question, evidence)       # the same builder every provider uses
    tr["prompt"] = {
        "hash": hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        "messages": messages,
    }
    usage = Usage()
    gen_started = time.perf_counter()
    outcome = generate_with_validation(provider, question, evidence, usage)
    metrics.GENERATION_LATENCY.observe(time.perf_counter() - gen_started)
    metrics.STAGE_LATENCY.labels(stage="generate").observe(time.perf_counter() - gen_started)
    tr["latency_ms"]["generate"] = _ms(gen_started)
    tr["generation"] = {
        "provider": provider.name,
        "model": settings.llm_model if provider.name != "stub" else "stub",
        "temperature": settings.temperature,
        "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out,
    }
    metrics.TOKENS.labels(direction="in").inc(usage.tokens_in)
    metrics.TOKENS.labels(direction="out").inc(usage.tokens_out)
    if outcome.citations_dropped:
        metrics.CITATIONS_DROPPED.inc(outcome.citations_dropped)
    answer = outcome.answer
    label = "answered"
    if outcome.fallback_reason:
        metrics.FALLBACKS.labels(reason=outcome.fallback_reason).inc()
        label = f"fallback:{outcome.fallback_reason}"
    elif not answer.answered_from_context:
        metrics.ABSTENTIONS.inc()
        fields.update(abstention=True)
        label = "abstained:model"
    fields.update(answered_from_context=answer.answered_from_context,
                  fallback=outcome.fallback_reason,
                  citations_dropped=outcome.citations_dropped)
    log.info("answered", extra=fields)
    tr["response"] = _response_record(answer, outcome.fallback_reason, outcome.citations_dropped)

    # 8. store the turn in the cache, if it is safe to serve to everyone
    response = _response(answer, retrieved, provider.name)
    stored = False
    if (cache is not None and vector is not None
            and cache_mod.should_cache(answer.answered_from_context, outcome.fallback_reason,
                                       followup)):
        cache.store(vector, include_old, response.model_dump())
        stored = True
    tr["cache"]["stored"] = stored
    return done(response, label)


def _failed(reason: str, exc: Exception, fields: dict[str, Any], provider_name: str) -> AskResponse:
    metrics.FALLBACKS.labels(reason=reason).inc()
    fields.update(fallback=reason)
    log.warning("answered", extra={**fields, "error": f"{type(exc).__name__}: {exc}"[:200]})
    return _response(fallback_answer(reason), [], provider_name)
