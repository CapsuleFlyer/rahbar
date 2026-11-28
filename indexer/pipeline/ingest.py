"""Verified, incremental ingestion (RAGOps A1 and A2). The Job's whole run, from files to Chroma.

    discover -> fingerprint -> verify (new or changed documents) -> chunk -> diff -> embed ->
    store -> archive/prune -> report

What makes it incremental. Every chunk stores `chash` (hash of its text), and every chunk of a
document stores `doc_sha256` (hash of the file) and `config_sig` (chunking and embedding
settings). A document whose file and settings are unchanged is skipped without even being
extracted: zero chunks embedded. A changed document is re-chunked and compared chunk by chunk:
identical text keeps its vector, only new text is embedded, and chunks that no longer exist are
deleted. A document that disappeared leaves no orphan chunks. An old version is archived: its
file moves to archive/ and its chunks stay, flagged `superseded`, so retrieval skips them but a
rollback can bring them back. The Job is still the only writer to Chroma.

Files are moved only after Chroma has been written, so a run that fails (the embedding service
is down, say) leaves the lake as it was and the retry reports every document again.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import embed as embed_mod
from . import verify
from .chunk import amplification, chunk, count_tokens
from .config import IndexerSettings
from .corpus import (
    DOC_SUFFIXES,
    Candidate,
    discover_entries,
    discover_unsupported,
    index_entries,
)
from .lake import Lake
from .models import Chunk, Document, text_hash
from .store import _get_existing, collection_metadata_for, refreshable, store

EXTRACT_VERSION = "3"      # bump when extract, clean or chunk logic changes: re-chunks everything
PAGE = 2000
BATCH = 100


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer.ingest", "msg": msg, **fields}), flush=True)


def config_sig(settings: IndexerSettings) -> str:
    import hashlib

    raw = "|".join([str(settings.chunk_size), str(settings.chunk_overlap),
                    settings.chunk_strategy, settings.embed_model, EXTRACT_VERSION])
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ------------------------------------------------------------------ reading Chroma
def fetch(collection: Any, where: dict[str, Any] | None = None,
          include: tuple[str, ...] = ("metadatas",)) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {"ids": [], "metadatas": [], "documents": []}
    offset = 0
    while True:
        kwargs: dict[str, Any] = {"include": list(include), "limit": PAGE, "offset": offset}
        if where:
            kwargs["where"] = where
        res = collection.get(**kwargs)
        got = list(res["ids"])
        out["ids"] += got
        for key in ("metadatas", "documents"):
            if res.get(key) is not None:
                out[key] += list(res[key])
        if len(got) < PAGE:
            return out
        offset += PAGE


@dataclass
class SourceState:
    count: int = 0
    sha: set[str] = field(default_factory=set)
    sigs: set[str] = field(default_factory=set)
    versions: set[str] = field(default_factory=set)
    superseded: set[bool] = field(default_factory=set)


def source_states(collection: Any) -> dict[str, SourceState]:
    states: dict[str, SourceState] = {}
    for meta in fetch(collection)["metadatas"]:
        m = meta or {}
        st = states.setdefault(str(m.get("source", "")), SourceState())
        st.count += 1
        st.sha.add(str(m.get("doc_sha256", "")))
        st.sigs.add(str(m.get("config_sig", "")))
        st.versions.add(str(m.get("doc_version", "")))
        st.superseded.add(bool(m.get("superseded", False)))
    return states


def fetch_vectors(collection: Any, ids: list[str]) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    # Several new chunks can have the same text hash and reuse one old chunk's vector.
    # Chroma requires IDs in a single get() request to be unique.
    unique_ids = list(dict.fromkeys(ids))
    for start in range(0, len(unique_ids), 500):
        res = collection.get(ids=unique_ids[start:start + 500], include=["embeddings"])
        embeddings = res.get("embeddings")
        if embeddings is None:
            continue
        for chunk_id, vector in zip(res["ids"], embeddings):
            found[chunk_id] = [float(x) for x in vector]
    return found


# ------------------------------------------------------------------ one document's diff
@dataclass
class DocPlan:
    source: str
    total: int
    unchanged: int = 0
    update_meta: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    reuse: list[tuple[Chunk, str]] = field(default_factory=list)      # (new chunk, old id)
    embed: list[Chunk] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)


def plan_document(collection: Any, source: str, chunks: list[Chunk]) -> DocPlan:
    """Compare a document's new chunks with what is stored for it, chunk by chunk."""
    old = fetch(collection, {"source": source}, ("documents", "metadatas"))
    old_by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    old_by_hash: dict[str, str] = {}
    for chunk_id, text, meta in zip(old["ids"], old["documents"], old["metadatas"]):
        m = dict(meta or {})
        h = str(m.get("chash") or text_hash(text or ""))
        old_by_id[chunk_id] = (h, m)
        old_by_hash.setdefault(h, chunk_id)
    plan = DocPlan(source=source, total=len(chunks))
    for c in chunks:
        want = c.metadata()
        prev = old_by_id.get(c.id)
        if prev and prev[0] == c.chash:
            if all(prev[1].get(k) == v for k, v in want.items()):
                plan.unchanged += 1
            else:
                plan.update_meta.append((c.id, {**prev[1], **want}))
        elif c.chash in old_by_hash:
            plan.reuse.append((c, old_by_hash[c.chash]))
        else:
            plan.embed.append(c)
    keep = {c.id for c in chunks}
    plan.delete = [i for i in old_by_id if i not in keep]
    return plan


def apply_plan(collection: Any, plan: DocPlan, new_vectors: dict[str, list[float]]) -> None:
    """Write one document: upsert first, delete stale ids last, so the store is never emptied."""
    old_vectors = fetch_vectors(collection, [old for _, old in plan.reuse]) if plan.reuse else {}
    rows = [(c, new_vectors[c.id]) for c in plan.embed]
    rows += [(c, old_vectors[old]) for c, old in plan.reuse]
    for start in range(0, len(rows), BATCH):
        part = rows[start:start + BATCH]
        collection.upsert(ids=[c.id for c, _ in part], documents=[c.text for c, _ in part],
                          embeddings=[v for _, v in part], metadatas=[c.metadata() for c, _ in part])
    for start in range(0, len(plan.update_meta), BATCH):
        part2 = plan.update_meta[start:start + BATCH]
        collection.update(ids=[i for i, _ in part2], metadatas=[m for _, m in part2])
    for start in range(0, len(plan.delete), BATCH):
        collection.delete(ids=plan.delete[start:start + BATCH])


def set_flags(collection: Any, source: str, version: str, superseded: bool) -> int:
    """Metadata-only change for a whole document (archive, restore, a version relabel)."""
    got = fetch(collection, {"source": source})
    ids: list[str] = []
    metas: list[dict[str, Any]] = []
    for chunk_id, meta in zip(got["ids"], got["metadatas"]):
        m = dict(meta or {})
        if m.get("superseded") != superseded or (version and m.get("doc_version") != version):
            m["superseded"] = superseded
            if version:
                m["doc_version"] = version
            ids.append(chunk_id)
            metas.append(m)
    for start in range(0, len(ids), BATCH):
        collection.update(ids=ids[start:start + BATCH], metadatas=metas[start:start + BATCH])
    return len(ids)


def source_counts(collection: Any) -> dict[str, int]:
    return {s: st.count for s, st in sorted(source_states(collection).items())}


# ------------------------------------------------------------------ the report
def _cell(check: dict[str, Any] | None) -> str:
    if check is None:
        return "-"
    return "pass" if check["passed"] else "FAIL"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Verification report {report['run_id']}", "",
             f"Corpus: `{report['corpus_dir']}` | documents: {report['summary']['documents']} "
             f"| verified now: {report['summary']['verified']} | unchanged: "
             f"{report['summary']['unchanged']}", "",
             "| Document | Quality | Completeness | Recency | Uniqueness | Outcome |",
             "| --- | --- | --- | --- | --- | --- |"]
    for d in report["documents"]:
        c = d["checks"]
        lines.append(f"| {d['source']} | {_cell(c.get('quality'))} | {_cell(c.get('completeness'))} "
                     f"| {_cell(c.get('recency'))} | {_cell(c.get('uniqueness'))} | {d['outcome']} |")
    lines += ["", "## Reasons", ""]
    for d in report["documents"]:
        lines.append(f"### {d['source']}  ({d['outcome']})")
        if d.get("note"):
            lines.append(f"- {d['note']}")
        for name in verify.CHECKS:
            if name in d["checks"]:
                ck = d["checks"][name]
                lines.append(f"- **{name}**: {'pass' if ck['passed'] else 'FAIL'}: {ck['reason']}")
        for w in d.get("warnings", []):
            lines.append(f"- **warning**: {w}")
        lines.append("")
    ing = report["ingest"]
    lines += ["## Ingestion counts", "",
              f"chunks embedded: **{ing['embedded']}** | reused: {ing['reused']} | unchanged: "
              f"{ing['unchanged']} | metadata updated: {ing['metadata_updated']} | deleted: "
              f"{ing['deleted']} | orphan chunks removed: {ing['orphans_removed']}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ the run
def run_ingestion(settings: IndexerSettings, client: Any) -> int:
    began = time.perf_counter()
    lake = Lake(settings.corpus_dir)
    writable = lake.prepare()
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    sig = config_sig(settings)
    candidates = discover_entries(settings.corpus_dir)
    existing = _get_existing(client, settings.collection)
    old_pin = (existing.metadata or {}) if existing is not None else {}
    full = existing is None or old_pin.get("embed_model") != settings.embed_model
    states = {} if full else source_states(existing)
    log("ingestion starting", run_id=run_id, documents=len(candidates), mode="full" if full
        else "incremental", config_sig=sig, lake_writable=writable)

    meta = {c.source: verify.read_metadata(c.path, c.entry, c.doc_version) for c in candidates}
    shas = {c.source: verify.file_sha256(c.path) for c in candidates}

    def version_of(c: Candidate) -> str:
        return meta[c.source]["doc_version"] or "unknown"

    history = lake.verified_rows(sig, shas)
    active = {c.source for c in candidates}
    # chunks that stay after this run; everything else stored belongs to a document that left
    kept = active | lake.archived_names() | lake.quarantined_names()

    unchanged: list[Candidate] = []
    flips: list[Candidate] = []
    to_verify: list[Candidate] = []
    for c in candidates:
        st = states.get(c.source)
        same_file = bool(st and st.count and st.sha == {shas[c.source]} and st.sigs == {sig})
        if same_file and writable and c.source not in history:
            to_verify.append(c)                    # its earlier results are gone: check it again
        elif (same_file and st and st.versions == {version_of(c)}
                and st.superseded == {c.superseded}):
            unchanged.append(c)
        elif same_file:
            flips.append(c)
        else:
            to_verify.append(c)

    def rank(c: Candidate) -> int:
        """0: the stored file itself, 1: an edit of an indexed document, 2: a new arrival."""
        st = states.get(c.source)
        if not (st and st.count):
            return 2
        return 0 if st.sha in ({shas[c.source]}, {""}) else 1

    def peer(c: Candidate, text_sha: str = "") -> verify.Peer:
        m = meta[c.source]
        return verify.Peer(c.source, m["title"], m["doc_version"], m["date"], shas[c.source],
                           text_sha, c.superseded, rank(c))

    # ---------------------------------------------------------------- A1: verify new or changed
    infos: dict[str, verify.DocInfo] = {}
    docs: dict[str, Document | None] = {}
    checks: dict[str, dict[str, verify.Check]] = {}
    warnings: dict[str, list[str]] = {}
    text_shas: dict[str, str] = {}
    batch_vectors: dict[str, tuple[list[float], str]] = {}
    store_vectors: dict[str, tuple[list[float], str]] | None = None

    # stored vectors of a file that has since been edited describe text that is being replaced
    stale = {c.source for c in to_verify if rank(c) == 1}

    def stored_peer(source: str) -> verify.Peer:
        """Title, version and date of an indexed document that is no longer active."""
        info = lake.archived_info(source)
        path = lake.archive / source
        if not path.is_file():
            path = next((copy for name, copy, _ in lake.quarantine_records() if name == source),
                        path)
        found = {"title": "", "doc_version": "", "date": ""}
        if path.is_file():                        # its .meta.json stays in the lake root
            found = verify.read_metadata(
                path, index_entries(settings.corpus_dir).get(source),
                sidecar=lake.root / f"{source}.meta.json")
        versions = states[source].versions - {"", "unknown"}
        return verify.Peer(source, str(info.get("title") or found["title"]),
                           found["doc_version"] or next(iter(sorted(versions)), ""),
                           found["date"], "")

    by_source = {c.source: c for c in candidates}
    for c in sorted(to_verify, key=lambda x: (rank(x), x.source)):
        info, doc = verify.load(c, settings)
        info.rank = rank(c)
        infos[c.source], docs[c.source] = info, doc
        text_shas[c.source] = info.text_sha256
        st = states.get(c.source)
        legacy = bool(st and st.count and st.sha <= {""})       # indexed before verification existed
        near: dict[str, float] = {}
        established = bool(st and st.count and st.sha == {shas[c.source]})  # passed when indexed
        if doc is not None and not legacy and not established:
            passages = verify.sample_passages(info.text)
            if passages:
                mean = verify.mean_vector(embed_mod.embed(passages, settings))
                if existing is not None and store_vectors is None:
                    store_vectors = verify.store_doc_vectors(
                        existing, [s for s in states if s in kept and s not in stale])
                others = {
                    s: v for s, v in {**(store_vectors or {}), **batch_vectors}.items()
                    if s != c.source and not verify.other_version(
                        info, peer(by_source[s]) if s in by_source else stored_peer(s))
                }
                near = verify.near_in_batch(mean, info.text, others, settings.near_dup_threshold)
                # a broken file must not make its intact copy look like the duplicate
                if (verify.check_quality(info, settings).passed
                        and verify.check_completeness(info).passed):
                    batch_vectors[c.source] = (mean, info.text)
        peers = [peer(o, text_shas.get(o.source, "")) for o in candidates if o.source != c.source]
        checks[c.source] = {
            "quality": verify.check_quality(info, settings),
            "completeness": verify.check_completeness(info),
            "uniqueness": verify.check_uniqueness(info, peers, near, settings.near_dup_threshold),
        }
        if established and checks[c.source]["uniqueness"].passed:
            checks[c.source]["uniqueness"].reason = (
                "no exact duplicate; the file is unchanged since it was indexed, so the "
                "near-duplicate comparison was not repeated")
        w = verify.injection_warning(info.text)
        warnings[c.source] = [w] if w else []

    # ---------------------------------------------------------------- recency, among survivors
    hard_fail = {s for s, ck in checks.items() if any(not x.passed for x in ck.values())}
    survivors = [c for c in candidates if c.source not in hard_fail]
    survivor_peers = [peer(c, text_shas.get(c.source, "")) for c in survivors]
    recency: dict[str, verify.Check] = {}
    for c in candidates:
        m = meta[c.source]
        probe = verify.Peer(c.source, m["title"], m["doc_version"], m["date"], shas[c.source],
                            "", c.superseded)
        recency[c.source] = verify.check_recency(probe, survivor_peers)
    for source in checks:
        checks[source]["recency"] = recency[source]

    # ---------------------------------------------------------------- verdicts (files move later)
    rows: list[dict[str, Any]] = []
    quarantined: dict[str, tuple[Path, dict[str, str]]] = {}
    archived_now: dict[str, str] = {}
    to_index: list[Candidate] = []
    for c in candidates:
        source = c.source
        row: dict[str, Any] = {
            "source": source, "title": meta[source]["title"], "doc_version": version_of(c),
            "date": meta[source]["date"], "sha256": shas[source],
            "checks": {n: {"passed": x.passed, "reason": x.reason}
                       for n, x in checks.get(source, {}).items()},
            "warnings": warnings.get(source, []),
        }
        if source not in checks:                                  # unchanged or flag-only
            rec = recency[source]
            past = history.get(source)
            if past:
                row["checks"] = dict(past["checks"])
                row["warnings"] = list(past.get("warnings", []))
                row["verified_in"] = past["run_id"]
                row["note"] = ("same file and settings as the indexed version: quality, "
                               f"completeness and uniqueness carried forward from run "
                               f"{past['run_id']}")
            else:                                  # only possible when the lake is read-only
                row["note"] = "same file and settings as the indexed version: not re-verified"
            row["checks"]["recency"] = {"passed": rec.passed, "reason": rec.reason}
            if not rec.passed:
                archived_now[source] = str(rec.extra["superseded_by"])
                row["outcome"] = "archived (old version)"
            else:
                row["outcome"] = "unchanged"
            rows.append(row)
            continue
        ordered = [checks[source][n] for n in verify.CHECKS]
        outcome = verify.verdict(ordered)
        probe_doc = docs[source]
        if outcome == "index" and probe_doc is not None:
            pieces = chunk(probe_doc, settings.chunk_size, settings.chunk_overlap,
                           strategy=settings.chunk_strategy)
            if not pieces:
                checks[source]["quality"] = verify.Check("quality", False,
                                                         "no text chunks could be built")
                row["checks"]["quality"] = {"passed": False, "reason": "no text chunks could be built"}
                outcome = "quarantine"
        if outcome == "quarantine":
            reasons = {n: x.reason for n, x in checks[source].items() if not x.passed}
            quarantined[source] = (c.path, reasons)
            row["outcome"] = "quarantined"
            row["note"] = ("; ".join(f"{n}: {r}" for n, r in reasons.items()))
        elif outcome == "archive":
            archived_now[source] = str(recency[source].extra["superseded_by"])
            row["outcome"] = "archived (old version)"
        else:
            to_index.append(c)
            row["outcome"] = "indexed"
        rows.append(row)

    unsupported = discover_unsupported(settings.corpus_dir)
    seen = {sha: source for source, sha in shas.items()}
    for path in unsupported:
        sha = verify.file_sha256(path)
        found = verify.unsupported_checks(path.suffix.lower(), sorted(DOC_SUFFIXES),
                                          seen.get(sha, ""))
        seen.setdefault(sha, path.name)
        reasons = {x.name: x.reason for x in found if not x.passed}
        quarantined[path.name] = (path, reasons)
        rows.append({"source": path.name, "title": "", "doc_version": "unknown", "date": "",
                     "sha256": sha, "warnings": [], "outcome": "quarantined",
                     "checks": {x.name: {"passed": x.passed, "reason": x.reason} for x in found},
                     "note": "; ".join(f"{n}: {r}" for n, r in reasons.items())})

    # ---------------------------------------------------------------- chunk what passed
    pieces_by_source: dict[str, list[Chunk]] = {}
    original_words = 0
    for c in to_index:
        doc = docs[c.source]
        assert doc is not None                       # only documents that were extracted pass
        pieces = [replace(p, doc_sha256=shas[c.source], config_sig=sig) for p in
                  chunk(doc, settings.chunk_size, settings.chunk_overlap,
                        strategy=settings.chunk_strategy)]
        words = sum(count_tokens(p.text) for p in doc.pages)
        original_words += words
        log("chunked", source=c.source, doc_version=version_of(c), superseded=c.superseded,
            pages=len(doc.pages), ocr_pages=sum(1 for p in doc.pages if p.ocr), words=words,
            chunks=len(pieces), amplification=amplification(doc, pieces))
        pieces_by_source[c.source] = pieces

    counts = {"embedded": 0, "reused": 0, "unchanged": 0, "metadata_updated": 0, "deleted": 0,
              "orphans_removed": 0}
    per_doc: dict[str, dict[str, int]] = {}
    total_chunks = 0

    all_chunks = [p for pieces in pieces_by_source.values() for p in pieces]
    if full and all_chunks:
        vectors = embed_mod.embed([p.text for p in all_chunks], settings)
        stored_words = sum(count_tokens(p.text) for p in all_chunks)
        log("embedded", chunks=len(all_chunks), dimension=embed_mod.embedding_dimension(vectors),
            embed_model=settings.embed_model,
            amplification=round(stored_words / original_words, 3) if original_words else 0.0,
            chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap,
            chunk_strategy=settings.chunk_strategy)
        total_chunks = store(all_chunks, vectors, settings, client)
        counts["embedded"] = len(all_chunks)
        for source, pieces in pieces_by_source.items():
            per_doc[source] = {"chunks": len(pieces), "embedded": len(pieces)}
    elif not full:
        assert existing is not None
        plans = [plan_document(existing, source, pieces)
                 for source, pieces in pieces_by_source.items()]
        texts = [c.text for p in plans for c in p.embed]
        vectors = embed_mod.embed(texts, settings) if texts else []
        by_id = {c.id: v for c, v in zip([c for p in plans for c in p.embed], vectors)}
        written = 0
        for plan in plans:
            apply_plan(existing, plan, by_id)
            per_doc[plan.source] = {"chunks": plan.total, "embedded": len(plan.embed),
                                    "reused": len(plan.reuse), "unchanged": plan.unchanged,
                                    "metadata_updated": len(plan.update_meta),
                                    "deleted": len(plan.delete)}
            counts["embedded"] += len(plan.embed)
            counts["reused"] += len(plan.reuse)
            counts["unchanged"] += plan.unchanged
            counts["metadata_updated"] += len(plan.update_meta)
            counts["deleted"] += len(plan.delete)
            written += len(plan.embed) + len(plan.reuse) + len(plan.update_meta) + len(plan.delete)
            log("document synced", source=plan.source, **per_doc[plan.source])
        for c in flips:                                         # same bytes, different flag
            counts["metadata_updated"] += set_flags(existing, c.source, version_of(c), c.superseded)
        for source in archived_now:                             # old versions: superseded, kept
            if source in states:
                counts["metadata_updated"] += set_flags(existing, source, "", True)
        for source in lake.archived_names() - active:   # an active file may reuse the name
            if source in states and states[source].superseded != {True}:
                counts["metadata_updated"] += set_flags(existing, source, "", True)
        # a document that left the lake leaves no chunks behind (a quarantined one keeps its
        # last good version until it passes again or someone deletes it)
        for source, st in states.items():
            if source and source not in kept | set(quarantined):
                existing.delete(where={"source": source})
                counts["orphans_removed"] += st.count
                log("orphans removed", source=source, chunks=st.count)
        changed = written or counts["metadata_updated"] or counts["orphans_removed"]
        if changed:
            dimension = int(old_pin.get("dimension", 0) or 0)
            existing.modify(metadata=refreshable(collection_metadata_for(
                int(existing.count()), dimension, settings)))
        total_chunks = int(existing.count())

    # ---------------------------------------------------------------- file moves, after the store
    by_row = {r["source"]: r for r in rows}
    for source, newer_source in archived_now.items():
        c = by_source[source]
        moved = lake.archive_file(c.path, newer_source, version_of(c), meta[source]["title"])
        log("archived", source=source, superseded_by=newer_source, moved=bool(moved))
    for source, (path, reasons) in quarantined.items():
        if not lake.quarantine_file(path, reasons):
            by_row[source]["outcome"] = "quarantine (not moved: read-only)"
        log("quarantined", source=source, reasons=by_row[source]["note"])
    if not full or all_chunks:                    # these passed: old failures no longer count
        for source in active - set(quarantined):
            lake.resolve_quarantine(source, f"a later file passed in run {run_id}")

    summary = {"documents": len(rows), "verified": len(to_verify) + len(unsupported),
               "unchanged": len(unchanged), "flag_only": len(flips), "indexed": len(to_index),
               "quarantined": len(quarantined), "archived": len(archived_now)}
    report = {"run_id": run_id, "corpus_dir": settings.corpus_dir, "config_sig": sig,
              "mode": "full" if full else "incremental",
              "thresholds": {"near_dup": settings.near_dup_threshold,
                             "min_chars_per_page": settings.min_chars_per_page,
                             "min_wordlike_ratio": settings.min_wordlike_ratio},
              "documents": rows, "summary": summary, "ingest": counts, "per_document": per_doc}
    markdown = render_markdown(report)
    paths = lake.write_report(run_id, report, markdown)
    print("\n" + markdown, flush=True)
    if full and not all_chunks:
        raise SystemExit("no document passed verification: nothing to index")
    log("ingest summary", seconds=round(time.perf_counter() - began, 1), chunks_in_store=total_chunks,
        report=paths, **{f"docs_{k}": v for k, v in summary.items()},
        **{f"chunks_{k}": v for k, v in counts.items()})
    return total_chunks

