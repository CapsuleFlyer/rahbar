"""POST /api/ask. The Ingress sends /api/* here unchanged, so the prefix stays."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from ..logjson import request_id_var
from ..schemas import (
    AskRequest,
    AskResponse,
    RetrieveRequest,
    RetrieveResponse,
    RetrievedChunk,
)
from ..services.answer import answer_question
from ..services.intent import wants_older_version

router = APIRouter(prefix="/api")


@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request, response: Response) -> AskResponse:
    state = request.app.state
    result = answer_question(body.question, state.retriever, state.provider, state.settings,
                             getattr(state, "cache", None), getattr(state, "trace", None),
                             no_cache=body.no_cache, include_evidence=body.include_evidence)
    response.headers["X-Cache"] = "HIT" if result.cached else "MISS"
    return result


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(body: RetrieveRequest, request: Request) -> RetrieveResponse:
    """Retrieval only, no model call: the same embedding, filter and top-k as /ask, so the
    component-level tests (recall, MRR, nDCG) measure what a real question gets."""
    state = request.app.state
    settings = state.settings
    include_old = wants_older_version(body.question)
    k = body.k or settings.top_k
    try:
        vector = state.retriever.embed_query(body.question)
        passages = state.retriever.retrieve(body.question, k=k, vector=vector,
                                            include_superseded=include_old)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"retrieval failed: {type(exc).__name__}") from exc
    return RetrieveResponse(
        request_id=request_id_var.get(), k=k, include_superseded=include_old,
        relevance_floor=settings.relevance_floor,
        retrieved=[RetrievedChunk(chunk_id=p.chunk_id, source=p.source, section=p.section,
                                  page=p.page, score=p.score, doc_version=p.doc_version,
                                  superseded=p.superseded) for p in passages])
