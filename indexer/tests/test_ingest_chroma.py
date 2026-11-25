"""The same ingestion behaviour against a REAL Chroma (in-process), not the fake.

Skipped when the full `chromadb` package is not installed (CI installs only the HTTP client).
The fake in tests/fakes.py is only trustworthy if the real API behaves the way it assumes, and
this is the test that checks that.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.test_ingest import fake_embed, latest_report, prose, row, seed_corpus, write_md

from pipeline.config import IndexerSettings, get_settings
from pipeline.ingest import run_ingestion, source_counts
from pipeline.lake import Lake

chromadb = pytest.importorskip("chromadb")
if not hasattr(chromadb, "EphemeralClient"):
    pytest.skip("needs the full chromadb package", allow_module_level=True)


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls = {"texts": 0}

    def counting(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
        calls["texts"] += len(texts)
        return fake_embed(texts, settings)

    monkeypatch.setattr("pipeline.embed.embed", counting)
    lake = tmp_path / "lake"
    lake.mkdir()
    cfg = replace(get_settings(), corpus_dir=str(lake), chunk_size=60, chunk_overlap=10,
                  embed_model="nomic-embed-text", collection=f"t-{uuid.uuid4().hex[:8]}")
    return {"lake": lake, "cfg": cfg, "client": chromadb.EphemeralClient(), "calls": calls}


def col(real: dict[str, Any]) -> Any:
    return real["client"].get_collection(real["cfg"].collection)


def test_real_chroma_incremental_cycle(real: dict[str, Any]) -> None:
    lake, cfg, client = real["lake"], real["cfg"], real["client"]
    seed_corpus(lake)
    total = run_ingestion(cfg, client)
    assert total > 6 and col(real).count() == total
    first = col(real).metadata["index_id"]

    before = real["calls"]["texts"]
    assert run_ingestion(cfg, client) == total
    assert real["calls"]["texts"] == before                      # zero embedded
    assert col(real).metadata["index_id"] == first               # the cache generation is kept

    write_md(lake, "beta.md", "Beta Rules", "1.1", prose(2, 200) + " " + prose(9, 40), "2026-02-01")
    run_ingestion(cfg, client)
    report = latest_report(lake)
    assert 0 < report["ingest"]["embedded"] < total / 2
    counts = source_counts(col(real))
    assert set(counts) == {"alpha.md", "beta.md", "gamma.md"}
    assert col(real).metadata["index_id"] != first

    (lake / "gamma.md").unlink()
    run_ingestion(cfg, client)
    assert "gamma.md" not in source_counts(col(real))
    assert col(real).get(where={"source": "gamma.md"})["ids"] == []   # proved by count: none left


def test_real_chroma_duplicates_and_near_duplicates(real: dict[str, Any]) -> None:
    lake, cfg, client = real["lake"], real["cfg"], real["client"]
    seed_corpus(lake)
    run_ingestion(cfg, client)
    (lake / "retired-beta.md").write_bytes((lake / "beta.md").read_bytes())
    words = prose(1, 200).split()
    words[5], words[80], words[140] = "changed", "edited", "altered"
    write_md(lake, "variant-alpha.md", "Alpha Rules (reworded)", "1.0", " ".join(words), "2026-01-10")
    write_md(lake, "delta.md", "Delta Rules", "1.0", prose(4, 200), "2026-01-13")
    run_ingestion(cfg, client)
    report = latest_report(lake)
    assert row(report, "retired-beta.md")["outcome"] == "quarantined"
    assert "near-duplicate of alpha.md" in row(report, "variant-alpha.md")["note"]
    assert row(report, "delta.md")["outcome"] == "indexed"
    assert set(source_counts(col(real))) == {"alpha.md", "beta.md", "gamma.md", "delta.md"}


def test_real_chroma_archive_filter_and_rollback(real: dict[str, Any]) -> None:
    lake, cfg, client = real["lake"], real["cfg"], real["client"]
    seed_corpus(lake)
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(11, 150), "2026-01-01")
    run_ingestion(cfg, client)
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", prose(12, 150), "2026-06-01")
    run_ingestion(cfg, client)

    def flag(source: str) -> set[bool]:
        got = col(real).get(where={"source": source}, include=["metadatas"])
        return {bool(m["superseded"]) for m in got["metadatas"]}

    assert flag("guide-v1.md") == {True} and flag("guide-v2.md") == {False}
    # retrieval's own filter: the superseded version is invisible to a normal query
    visible = col(real).get(where={"superseded": False}, include=["metadatas"])["metadatas"]
    assert "guide-v1.md" not in {m["source"] for m in visible}

    before = real["calls"]["texts"]
    Lake(str(lake)).restore("guide-v1.md")
    run_ingestion(cfg, client)
    assert flag("guide-v1.md") == {False} and flag("guide-v2.md") == {True}
    assert real["calls"]["texts"] == before                       # a rollback embeds nothing
