"""Stage 1b: Verify (RAGOps A1). Runs after extraction and before chunking.

Four checks per document, each with a pass or fail and a reason:

  quality       the text is there and readable (not empty, not garbled, extraction worked)
  completeness  title, source, a date or a version and a page count exist, and the file is
                not cut off (a PDF without its end marker, a text that stops mid-sentence)
  recency       a NEWER version of the same document is not already present
  uniqueness    not an exact duplicate (SHA-256 of the file or of the text) and not a
                near-duplicate (cosine similarity of document vectors, confirmed by shared wording)

Verdict: any failure of quality, completeness or uniqueness quarantines the document. A
recency failure means the document is an OLD version: it is archived, not quarantined (it
stays in the store, flagged superseded, so it can be restored).

A prompt-injection pattern in a document is only a WARNING here. The document is indexed, and
the query-time rail (api/app/guardrails.py) flags and neutralises it, so the defence can be
shown working. Everything is standard library plus the stages already in this package.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import IndexerSettings
from .corpus import Candidate, front_matter
from .models import Document

CHECKS = ("quality", "completeness", "recency", "uniqueness")
SAMPLE_WORDS = 250
SAMPLES = 3

_WORDLIKE = re.compile(r"^[(\[\"'“‘]*[A-Za-z][A-Za-z'’/\-]*[)\]\"'”’.,;:!?%]*$")
_NUMBERLIKE = re.compile(r"^[(\[]*\d[\d.,:/%+\-×x]*[)\].,;:!?%]*$")
_NEUTRAL = re.compile(r"^[\W_]+$")                 # |, ---, bullets: table and layout marks
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•●▪]|\d{1,3}[.)]|\(\w{1,4}\))\s+\S")
# a list item that ends on one of these was cut off, full stop or not
_DANGLING = {"a", "an", "the", "and", "or", "of", "to", "with", "for"}
_INJECTION = re.compile(
    r"\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:previous|prior|above|earlier|all|your)\b"
    r".{0,40}\b(?:instruction|prompt|rule|message)s?\b|\byou are now\b|</?\s*evidence\b",
    re.I | re.S)


@dataclass
class Check:
    name: str
    passed: bool
    reason: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DocInfo:
    path: Path
    source: str
    title: str = ""
    doc_version: str = ""
    date: str = ""
    superseded: bool = False             # flagged in _index.json or front matter
    rank: int = 2                        # 0 unchanged and indexed, 1 edited, 2 new arrival
    sha256: str = ""
    text: str = ""
    text_sha256: str = ""
    pages: int = 0
    ocr_pages: int = 0
    error: str = ""                      # extraction failed

    @property
    def key(self) -> str:
        return title_key(self.title)


# ------------------------------------------------------------------ metadata
def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def title_key(title: str) -> str:
    """The same document under any version: lower-case, no years, versions or brackets."""
    text = re.sub(r"\([^)]*\)", " ", title.lower())
    text = re.sub(r"\bv?\d+(?:\.\d+)*\b", " ", text)
    return " ".join(re.sub(r"[^a-z]+", " ", text).split())


def _fill(meta: dict[str, str], title: str = "", version: str = "", date: str = "") -> None:
    if title and not meta["title"]:
        meta["title"] = title.strip()
    if version and version.lower() != "unknown" and not meta["doc_version"]:
        meta["doc_version"] = str(version).strip()
    if date and not meta["date"]:
        meta["date"] = str(date).strip()


def read_metadata(path: Path, entry: dict[str, Any] | None, index_version: str = "",
                  sidecar: Path | None = None) -> dict[str, str]:
    """Title, version and date, from the first place that has each: the _index.json row, a
    `<file>.meta.json` sidecar, Markdown front matter or its first heading, the PDF's own info."""
    meta = {"title": "", "doc_version": "", "date": ""}
    if entry:
        _fill(meta, str(entry.get("name", "")), str(entry.get("doc_version", "")),
              str(entry.get("date", "")))
    sidecar = sidecar or Path(str(path) + ".meta.json")
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            _fill(meta, str(data.get("title", "")),
                  str(data.get("doc_version") or data.get("version") or ""),
                  str(data.get("date", "")))
        except ValueError:
            pass
    suffix = path.suffix.lower()
    if suffix == ".md":
        fm = front_matter(path)
        _fill(meta, fm.get("title", ""), fm.get("doc_version") or fm.get("version") or "",
              fm.get("date", ""))
        if not meta["title"]:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("# "):
                    _fill(meta, title=line[2:])
                    break
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader

            info = PdfReader(str(path)).metadata
            if info:
                created = info.creation_date
                _fill(meta, title=str(info.title or ""),
                      date=created.date().isoformat() if created else "")
        except Exception:                      # a damaged PDF simply has no info
            pass
    _fill(meta, version=index_version)
    return meta


def load(candidate: Candidate, settings: IndexerSettings) -> tuple[DocInfo, Document | None]:
    """Extract and clean one document, recording (not raising) an extraction failure."""
    from .clean import clean
    from .extract import extract

    meta = read_metadata(candidate.path, candidate.entry, candidate.doc_version)
    info = DocInfo(path=candidate.path, source=candidate.source, title=meta["title"],
                   doc_version=meta["doc_version"], date=meta["date"],
                   superseded=candidate.superseded, sha256=file_sha256(candidate.path))
    try:
        doc = clean(extract(str(candidate.path), meta["doc_version"] or "unknown",
                            candidate.superseded, ocr_lang=settings.ocr_lang,
                            ocr_dpi=settings.ocr_dpi))
    except Exception as exc:                   # corrupt or truncated files land here
        info.error = f"{type(exc).__name__}: {exc}"[:200]
        return info, None
    info.pages = len(doc.pages)
    info.ocr_pages = sum(1 for p in doc.pages if p.ocr)
    info.text = "\n".join(p.text for p in doc.pages)
    info.text_sha256 = hashlib.sha256(" ".join(info.text.split()).encode()).hexdigest()
    return info, doc


# ------------------------------------------------------------------ the four checks
def wordlike_ratio(text: str) -> float:
    good = bad = 0
    for token in text.split():
        if _NEUTRAL.match(token):
            continue
        if _WORDLIKE.match(token) or _NUMBERLIKE.match(token):
            good += 1
        else:
            bad += 1
    return good / (good + bad) if good + bad else 0.0


def check_quality(info: DocInfo, settings: IndexerSettings) -> Check:
    if info.error:
        return Check("quality", False, f"extraction failed: {info.error}")
    chars = len(info.text.strip())
    if info.pages == 0 or chars == 0:
        return Check("quality", False, "no text could be extracted: the document is empty")
    per_page = chars / info.pages
    if per_page < settings.min_chars_per_page:
        return Check("quality", False, f"almost empty: {per_page:.0f} characters per page "
                                       f"(minimum {settings.min_chars_per_page})")
    replaced = info.text.count("\ufffd") / max(1, chars)
    if replaced > 0.01:
        return Check("quality", False, f"garbled: {100 * replaced:.1f}% replacement characters")
    ratio = wordlike_ratio(info.text)
    if ratio < settings.min_wordlike_ratio:
        return Check("quality", False, f"garbled: only {100 * ratio:.0f}% of tokens look like "
                                       f"words or numbers (minimum "
                                       f"{100 * settings.min_wordlike_ratio:.0f}%)")
    ocr = f", {info.ocr_pages} read by OCR" if info.ocr_pages else ""
    return Check("quality", True, f"{info.pages} pages{ocr}, {per_page:.0f} characters per page, "
                                  f"{100 * ratio:.0f}% word-like tokens")


def ends_in_list_item(text: str) -> bool:
    """Is the last line a list item, or the indented continuation of one?"""
    block = re.split(r"\n\s*\n", text.rstrip())[-1].split("\n")
    if block[-1].split()[-1].lower() in _DANGLING:
        return False
    for line in reversed(block):
        if _LIST_ITEM.match(line):
            return True
        if not line[:1].isspace():
            return False
    return False


def truncation(info: DocInfo) -> str:
    suffix = info.path.suffix.lower()
    if suffix == ".pdf":
        with info.path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - 2048))
            if b"%%EOF" not in handle.read():
                return "the PDF is cut off: its end-of-file marker is missing"
        return ""
    stripped = info.text.rstrip()
    if stripped and stripped[-1].isalnum() and ends_in_list_item(stripped):
        return ""                              # list items usually carry no full stop
    if stripped and (stripped[-1].isalnum() or stripped[-1] in ",;"):
        return f"the text stops mid-sentence (last words: ...{stripped[-30:]!r})"
    return ""


def check_completeness(info: DocInfo) -> Check:
    missing = []
    if not info.source:
        missing.append("source")
    if not info.title:
        missing.append("title")
    if not (info.doc_version or info.date):
        missing.append("date or version")
    if info.pages < 1:
        missing.append("page count")
    problems = []
    if missing:
        problems.append("missing metadata: " + ", ".join(missing))
    cut = truncation(info)
    if cut:
        problems.append(cut)
    if problems:
        return Check("completeness", False, "; ".join(problems))
    stamp = f"version {info.doc_version}" if info.doc_version else f"dated {info.date}"
    return Check("completeness", True, f"title, source, {stamp} and {info.pages} page(s) present; "
                                       f"text not truncated")


# ------------------------------------------------------------------ peers, recency, uniqueness
@dataclass
class Peer:
    source: str
    title: str
    doc_version: str
    date: str
    sha256: str
    text_sha256: str = ""
    superseded: bool = False
    rank: int = 2

    @property
    def key(self) -> str:
        return title_key(self.title)


def _nums(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def newer(a: Peer | DocInfo, b: Peer | DocInfo) -> bool | None:
    """Is `a` a newer version than `b`? None when they cannot be compared."""
    va, vb = _nums(a.doc_version), _nums(b.doc_version)
    if va and vb and va != vb:
        return va > vb
    da, db = _nums(a.date), _nums(b.date)
    if da and db and da != db:
        return da > db
    return None


def other_version(a: Peer | DocInfo, b: Peer | DocInfo) -> bool:
    """Are these two editions of one document (so their shared wording is expected)? The titles
    must match and the version numbers differ. Without two version numbers the dates must differ
    and the titles be written identically, so "Title (reworded)" is still compared."""
    if not a.key or a.key != b.key:
        return False
    va, vb = _nums(a.doc_version), _nums(b.doc_version)
    if va and vb:
        return va != vb
    da, db = _nums(a.date), _nums(b.date)
    return bool(da and db and da != db) and a.title.strip().lower() == b.title.strip().lower()


def check_recency(info: DocInfo | Peer, peers: list[Peer]) -> Check:
    later = [p for p in peers if p.source != info.source and p.key == title_key(info.title)
             and newer(p, info)]
    if not later:
        return Check("recency", True, "no newer version of this document is present")
    top = max(later, key=lambda p: (_nums(p.doc_version), _nums(p.date)))
    if info.superseded:
        return Check("recency", True, f"already marked superseded; the newer version is "
                                      f"{top.source} (v{top.doc_version})",
                     {"superseded_by": top.source})
    return Check("recency", False, f"a newer version exists: {top.source} (v{top.doc_version})",
                 {"superseded_by": top.source})


def check_uniqueness(info: DocInfo, peers: list[Peer],
                     near: dict[str, float], threshold: float) -> Check:
    for p in peers:
        if p.source == info.source or (p.rank, p.source) > (info.rank, info.source):
            continue          # the original: indexed and unchanged, then edited, then first by name
        if p.sha256 == info.sha256:
            return Check("uniqueness", False,
                         f"exact duplicate of {p.source} (same SHA-256 {info.sha256[:12]})")
        if p.text_sha256 and p.text_sha256 == info.text_sha256:
            return Check("uniqueness", False, f"exact duplicate of {p.source} (identical text)")
    if near:
        other, sim = max(near.items(), key=lambda kv: kv[1])
        return Check("uniqueness", False,
                     f"near-duplicate of {other} (cosine {sim:.3f}, threshold {threshold})")
    return Check("uniqueness", True, "no exact or near duplicate found")


# ------------------------------------------------------------------ near-duplicate sampling
def sample_passages(text: str) -> list[str]:
    """Up to three passages (start, middle, end) of about 250 words: what gets embedded to
    compare documents without embedding all of them."""
    words = text.split()
    if len(words) <= SAMPLE_WORDS:
        return [" ".join(words)] if words else []
    starts = sorted({0, max(0, len(words) // 2 - SAMPLE_WORDS // 2),
                     max(0, len(words) - SAMPLE_WORDS)})
    return [" ".join(words[s:s + SAMPLE_WORDS]) for s in starts[:SAMPLES]]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def mean_vector(vectors: list[list[float]]) -> list[float]:
    return [sum(col) / len(vectors) for col in zip(*vectors)] if vectors else []


def shingles(text: str, size: int = 3) -> set[int]:
    words = text.lower().split()
    return {hash(tuple(words[i:i + size])) for i in range(max(0, len(words) - size + 1))}


def overlap(a: str, b: str) -> float:
    """Share of the smaller text's 3-word shingles that also appear in the other."""
    sa, sb = shingles(a), shingles(b)
    return len(sa & sb) / min(len(sa), len(sb)) if sa and sb else 0.0


LEXICAL_MIN = 0.5     # embeddings find the candidate; shared wording confirms it is a near-copy


def store_doc_vectors(collection: Any, sources: list[str],
                      max_chunks: int = 12) -> dict[str, tuple[list[float], str]]:
    """A document-level vector for each indexed document: the mean of up to a dozen of its
    stored chunk vectors (evenly spaced), plus the text of those chunks for the wording check."""
    out: dict[str, tuple[list[float], str]] = {}
    for source in sources:
        try:
            ids = list(collection.get(where={"source": source}, include=["metadatas"])["ids"])
            if not ids:
                continue
            pick = ids[::max(1, len(ids) // max_chunks)][:max_chunks]
            res = collection.get(ids=pick, include=["embeddings", "documents"])
            vectors = [[float(x) for x in e] for e in res["embeddings"]]
            out[source] = (mean_vector(vectors), " ".join(str(d) for d in res["documents"]))
        except Exception:                       # a source we cannot read is simply not compared
            continue
    return out


def near_in_batch(vector: list[float], text: str, others: dict[str, tuple[list[float], str]],
                  threshold: float) -> dict[str, float]:
    """Documents whose vector is at or above the threshold AND that share most of their wording.
    Topic similarity alone (two editions of one rule book) is not a duplicate."""
    return {src: c for src, (v, t) in others.items()
            if (c := cosine(vector, v)) >= threshold and overlap(text, t) >= LEXICAL_MIN}


# ------------------------------------------------------------------ the verdict
def injection_warning(text: str) -> str:
    return ("an instruction-like passage was found (a prompt-injection pattern); the document "
            "is indexed and the query-time guardrail will flag it") if _INJECTION.search(text) else ""


def unsupported_checks(suffix: str, supported: list[str], duplicate_of: str) -> list[Check]:
    """The four results for a file type extraction cannot read: it cannot pass, and says why."""
    kind = suffix or "(no extension)"
    return [
        Check("quality", False, f"unsupported file type {kind}: no text can be extracted "
                                f"(supported: {', '.join(supported)})"),
        Check("completeness", False, "title, version and page count cannot be read from this "
                                     "file type"),
        Check("recency", True, "no version information can be read, so no newer version is "
                               "detected"),
        Check("uniqueness", not duplicate_of,
              f"exact duplicate of {duplicate_of} (same SHA-256)" if duplicate_of
              else "no exact duplicate by SHA-256 (there is no text to compare)"),
    ]


def verdict(checks: list[Check]) -> str:
    """index, archive (an old version) or quarantine (anything else wrong)."""
    if any(not c.passed for c in checks if c.name != "recency"):
        return "quarantine"
    if any(not c.passed for c in checks if c.name == "recency"):
        return "archive"
    return "index"
