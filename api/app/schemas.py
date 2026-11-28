"""The contracts. Change them only with your partner's review: the UI, the
evaluation script and your tests all depend on these shapes.

`Answer` is what the model must produce (section 3.4). `AskResponse` is what
the API returns to the UI and to eval/run_eval.py. The model's `reasoning` is
never sent to the user.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    # Evaluation hooks (RAGOps part B). Both default to off, so normal users never see them.
    no_cache: bool = False            # skip the semantic cache: honest latency, fresh answer
    include_evidence: bool = False    # return the passage texts the model was shown


class Passage(BaseModel):
    """One retrieved chunk, as the retriever hands it to the generator."""

    chunk_id: str
    text: str
    source: str
    section: str
    page: int | None = None
    score: float = Field(description="Similarity, higher is closer (1 - cosine distance).")
    # Recorded in the trace (RAGOps D1): which version of the document this came from.
    doc_version: str | None = None
    superseded: bool | None = None


class Citation(BaseModel):
    source: str
    section: str
    page: int | None = None


class Answer(BaseModel):
    """The model's output contract. Send its JSON schema to the model, then validate."""

    reasoning: str
    answer: str
    citations: list[Citation]
    answered_from_context: bool
    confidence: Literal["high", "medium", "low"]


class RetrievedRef(BaseModel):
    """What the response says was retrieved. eval/run_eval.py scores against this."""

    chunk_id: str
    source: str
    section: str
    page: int | None = None
    score: float


class EvidenceText(BaseModel):
    chunk_id: str
    source: str
    section: str
    page: int | None = None
    text: str


class AskResponse(BaseModel):
    request_id: str
    answer: str
    citations: list[Citation]
    answered_from_context: bool
    confidence: Literal["high", "medium", "low"]
    retrieved: list[RetrievedRef]
    provider: str
    # Contract change (documented in ADR): the UI shows a cache chip when this is true.
    cached: bool = False
    evidence: list[EvidenceText] | None = None     # only when the request set include_evidence


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    k: int | None = Field(default=None, ge=1, le=50)


class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str
    section: str
    page: int | None = None
    score: float
    doc_version: str | None = None
    superseded: bool | None = None


class RetrieveResponse(BaseModel):
    """Retrieval only (no model call): what the component-level tests measure."""

    request_id: str
    k: int
    include_superseded: bool
    relevance_floor: float
    retrieved: list[RetrievedChunk]
