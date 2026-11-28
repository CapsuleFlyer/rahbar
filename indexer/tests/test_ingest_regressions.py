"""Regressions found by reviewing Part A (RAGOps A1 and A2), each reproduced before it was fixed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.test_ingest import (
    collection,
    fake_embed,
    latest_report,
    prose,
    row,
    seed_corpus,
    write_md,
)
from tests.pdfutil import make_pdf

from pipeline import ops, verify
from pipeline.config import IndexerSettings
from pipeline.ingest import fetch_vectors, run_ingestion, source_counts
from pipeline.lake import Lake

CHECK_NAMES = set(verify.CHECKS)


def edited(text: str) -> str:
    words = text.split()
    words[10], words[90] = "changed", "edited"
    return " ".join(words)


def sources(env: dict[str, Any]) -> set[str]:
    return set(source_counts(collection(env)))


# ---------------------------------------------------------------- a newer, lightly edited version
@pytest.mark.parametrize("new_name", ["guide-v2.md", "a-guide-v2.md"])   # sorts after and before
def test_a_lightly_edited_newer_version_replaces_the_old_one(env: dict[str, Any],
                                                             new_name: str) -> None:
    lake = env["lake"]
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(11, 200), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, new_name, "Field Guide", "2.0", edited(prose(11, 200)), "2026-06-01")
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    assert row(report, new_name)["outcome"] == "indexed", row(report, new_name)
    assert row(report, "guide-v1.md")["outcome"] == "archived (old version)"
    flags = {m["source"]: m["superseded"] for _, _, m in collection(env).rows.values()}
    assert flags == {"guide-v1.md": True, new_name: False}


def test_two_versions_arriving_together_keep_the_newer_one(env: dict[str, Any]) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(11, 200), "2026-01-01")
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", edited(prose(11, 200)), "2026-06-01")
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    assert row(report, "guide-v1.md")["outcome"] == "archived (old version)"
    assert row(report, "guide-v2.md")["outcome"] == "indexed"


def test_a_newer_version_of_an_archived_document_is_not_a_duplicate(env: dict[str, Any]) -> None:
    lake = env["lake"]
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(11, 200), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", prose(12, 200), "2026-03-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-v3.md", "Field Guide", "3.0", edited(prose(11, 200)), "2026-06-01")
    run_ingestion(env["cfg"], env["client"])
    assert row(latest_report(lake), "guide-v3.md")["outcome"] == "indexed"


def test_a_reworded_copy_with_the_same_version_and_a_later_date_is_still_a_duplicate(
        env: dict[str, Any]) -> None:
    lake = env["lake"]
    write_md(lake, "guide.md", "Field Guide", "1.0", prose(11, 200), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-copy.md", "Field Guide", "1.0", edited(prose(11, 200)), "2026-02-01")
    run_ingestion(env["cfg"], env["client"])
    assert row(latest_report(lake), "guide-copy.md")["outcome"] == "quarantined"
    assert sources(env) == {"guide.md"}


# ---------------------------------------------------------------- rename
def test_a_renamed_document_stays_indexed(env: dict[str, Any]) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    run_ingestion(env["cfg"], env["client"])
    count = source_counts(collection(env))["alpha.md"]
    (lake / "alpha.md").rename(lake / "alpha-renamed.md")
    run_ingestion(env["cfg"], env["client"])
    assert row(latest_report(lake), "alpha-renamed.md")["outcome"] == "indexed"
    assert sources(env) == {"alpha-renamed.md", "beta.md", "gamma.md"}
    assert source_counts(collection(env))["alpha-renamed.md"] == count


def test_a_bad_file_does_not_make_the_good_copy_a_duplicate(env: dict[str, Any]) -> None:
    lake = env["lake"]
    body = prose(31, 200)
    write_md(lake, "a-cut.md", "Cut Guide", "1.0", body[:-1], "2026-01-01")      # truncated
    write_md(lake, "b-good.md", "Good Guide", "1.0", body, "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    assert row(report, "a-cut.md")["outcome"] == "quarantined"
    assert row(report, "b-good.md")["outcome"] == "indexed"


# ---------------------------------------------------------------- orphans after quarantine
def test_quarantine_repair_and_deletion_leave_no_orphans(env: dict[str, Any]) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    run_ingestion(env["cfg"], env["client"])
    good = (lake / "alpha.md").read_text(encoding="utf-8")
    for _ in range(2):                                    # twice: the second record is numbered
        (lake / "alpha.md").write_text(good.rstrip()[:-1], encoding="utf-8")
        run_ingestion(env["cfg"], env["client"])
        assert "alpha.md" in sources(env)                 # the last good version is kept
        assert Lake(str(lake)).quarantined_names() == {"alpha.md"}
    (lake / "alpha.md").write_text(good, encoding="utf-8")
    run_ingestion(env["cfg"], env["client"])
    assert Lake(str(lake)).quarantined_names() == set()
    assert (lake / "quarantine" / "alpha.md").is_file()   # the bad copy is kept for the record
    (lake / "alpha.md").unlink()
    run_ingestion(env["cfg"], env["client"])
    assert "alpha.md" not in sources(env)


def test_ops_delete_removes_a_quarantined_documents_old_chunks(
        env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    run_ingestion(env["cfg"], env["client"])
    (lake / "alpha.md").write_text("# Alpha Rules\n\ncut off", encoding="utf-8")
    run_ingestion(env["cfg"], env["client"])
    monkeypatch.setattr(ops, "get_settings", lambda: env["cfg"])
    assert ops.main(["delete", "alpha.md"]) == 0
    run_ingestion(env["cfg"], env["client"])
    assert "alpha.md" not in sources(env)
    assert ops.main(["delete", "alpha.md"]) == 1


# ---------------------------------------------------------------- vector reuse
def test_fetch_vectors_deduplicates_ids_before_querying_chroma() -> None:
    class DuplicateRejectingCollection:
        def get(self, ids: list[str], include: list[str]) -> dict[str, Any]:
            assert len(ids) == len(set(ids))
            assert include == ["embeddings"]
            return {"ids": ids, "embeddings": [[1.0, 2.0] for _ in ids]}

    vectors = fetch_vectors(DuplicateRejectingCollection(),
                            ["old-1", "old-1", "old-2", "old-1"])
    assert vectors == {"old-1": [1.0, 2.0], "old-2": [1.0, 2.0]}


# ---------------------------------------------------------------- chunk ids
@pytest.mark.parametrize("other", ["weather.txt", "Weather.html"])
def test_files_sharing_a_stem_do_not_overwrite_each_other(env: dict[str, Any], other: str) -> None:
    lake = env["lake"]
    write_md(lake, "weather.md", "Weather", "1.0", prose(41, 200), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    before = source_counts(collection(env))["weather.md"]
    (lake / other).write_text(f"<p>{prose(42, 200)}</p>" if other.endswith(".html")
                              else prose(42, 200), encoding="utf-8")
    (lake / f"{other}.meta.json").write_text('{"title": "Storms", "version": "1.0"}')
    run_ingestion(env["cfg"], env["client"])
    counts = source_counts(collection(env))
    assert counts["weather.md"] == before and counts[other] > 0


def test_chunks_stored_under_the_old_ids_are_renamed_without_embedding(
        env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seed_corpus(env["lake"])
    monkeypatch.setattr("pipeline.ingest.EXTRACT_VERSION", "2")
    run_ingestion(env["cfg"], env["client"])
    rows = collection(env).rows
    for n, key in enumerate(list(rows)):                  # the ids the previous release wrote
        rows[f"old-{n:04d}"] = rows.pop(key)
    total = len(rows)
    monkeypatch.undo()
    monkeypatch.setattr("pipeline.embed.embed", fake_embed)
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(env["lake"])
    assert report["ingest"]["embedded"] == 0 and report["ingest"]["reused"] == total
    assert len(rows) == total and not any(k.startswith("old-") for k in rows)


# ---------------------------------------------------------------- truncation and lists
@pytest.mark.parametrize("tail", [
    "- Rope\n- Lantern",
    "* One torch",
    "1. Pack the bags\n2. Leave at dawn",
    "- A long item that wraps\n  onto a second line",
])
def test_a_document_ending_in_a_list_is_not_truncated(env: dict[str, Any], tail: str) -> None:
    write_md(env["lake"], "kit.md", "Kit", "1.0", prose(51, 80) + "\n\n" + tail, "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    r = row(latest_report(env["lake"]), "kit.md")
    assert r["outcome"] == "indexed", r["checks"]["completeness"]


@pytest.mark.parametrize("tail", [
    "and then the party walked into the",
    "- Rope\n- Lantern,",
    "- Rope\n- A flask of",
    "- Rope\n\nThe next part of the road",
])
def test_a_cut_off_document_is_still_truncated(env: dict[str, Any], tail: str) -> None:
    seed_corpus(env["lake"])
    write_md(env["lake"], "kit.md", "Kit", "1.0", prose(51, 80) + "\n\n" + tail, "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    r = row(latest_report(env["lake"]), "kit.md")
    assert not r["checks"]["completeness"]["passed"], r


# ---------------------------------------------------------------- the report
def test_an_unchanged_run_reports_all_four_checks(env: dict[str, Any]) -> None:
    seed_corpus(env["lake"])
    run_ingestion(env["cfg"], env["client"])
    before = dict(env["calls"])
    for _ in range(2):
        run_ingestion(env["cfg"], env["client"])
        report = latest_report(env["lake"])
        for r in report["documents"]:
            assert set(r["checks"]) == CHECK_NAMES and r["outcome"] == "unchanged"
            assert "carried forward" in r["note"]
    assert env["calls"] == before


def test_lost_reports_mean_the_documents_are_verified_again(env: dict[str, Any]) -> None:
    seed_corpus(env["lake"])
    run_ingestion(env["cfg"], env["client"])
    for path in (env["lake"] / "reports").iterdir():
        path.unlink()
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(env["lake"])
    assert report["ingest"]["embedded"] == 0
    assert all(set(r["checks"]) == CHECK_NAMES and r["outcome"] == "indexed"
               for r in report["documents"])


def test_runs_in_the_same_second_keep_separate_reports(
        env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    seed_corpus(env["lake"])
    monkeypatch.setattr("pipeline.ingest.time.strftime", lambda *_a: "20260101T000000Z")
    run_ingestion(env["cfg"], env["client"])
    run_ingestion(env["cfg"], env["client"])
    assert len(list((env["lake"] / "reports").glob("*.json"))) == 2
    assert latest_report(env["lake"])["summary"]["unchanged"] == 3


# ---------------------------------------------------------------- unsupported files
def test_an_unsupported_file_is_quarantined_and_reported(env: dict[str, Any]) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    (lake / "house-rules.docx").write_bytes(b"PK\x03\x04 not really a document")
    for ignored in (".DS_Store", "golden.fixture.yaml", "README.docx"):
        (lake / ignored).write_text("x")
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    r = row(report, "house-rules.docx")
    assert r["outcome"] == "quarantined" and set(r["checks"]) == CHECK_NAMES
    assert "unsupported file type" in r["checks"]["quality"]["reason"]
    assert (lake / "quarantine" / "house-rules.docx").is_file()
    assert {d["source"] for d in report["documents"]} == {
        "alpha.md", "beta.md", "gamma.md", "house-rules.docx"}
    assert all((lake / n).is_file() for n in (".DS_Store", "golden.fixture.yaml", "README.docx"))


# ---------------------------------------------------------------- a run that fails part way
@pytest.mark.parametrize("fail_on_call", ["first", "last"])
def test_a_failed_run_moves_nothing_so_the_retry_reports_everything(
        env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fail_on_call: str) -> None:
    lake = env["lake"]
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(11, 150), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", prose(12, 150), "2026-06-01")
    write_md(lake, "bad.md", None, None, prose(7, 80))

    def down(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
        is_chunk_call = any(t.startswith("Field Guide\n") for t in texts)
        if fail_on_call == "first" or is_chunk_call:
            raise RuntimeError("ollama is down")
        return fake_embed(texts, settings)

    monkeypatch.setattr("pipeline.embed.embed", down)
    with pytest.raises(RuntimeError):
        run_ingestion(env["cfg"], env["client"])
    assert (lake / "bad.md").is_file() and (lake / "guide-v1.md").is_file()

    monkeypatch.setattr("pipeline.embed.embed", fake_embed)
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    assert row(report, "bad.md")["outcome"] == "quarantined"
    assert row(report, "guide-v1.md")["outcome"] == "archived (old version)"
    assert (lake / "quarantine" / "bad.md").is_file()
    assert (lake / "archive" / "guide-v1.md").is_file()


def test_a_first_run_where_everything_fails_still_writes_a_report(env: dict[str, Any]) -> None:
    write_md(env["lake"], "bad.md", None, None, prose(7, 80))
    with pytest.raises(SystemExit):
        run_ingestion(env["cfg"], env["client"])
    assert row(latest_report(env["lake"]), "bad.md")["outcome"] == "quarantined"
    assert (env["lake"] / "quarantine" / "bad.md").is_file()


def test_an_archived_name_reused_by_an_active_file_is_not_flagged_superseded(
        env: dict[str, Any]) -> None:
    lake: Path = env["lake"]
    write_md(lake, "guide.md", "Field Guide", "1.0", prose(11, 150), "2026-01-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", prose(12, 150), "2026-06-01")
    run_ingestion(env["cfg"], env["client"])
    write_md(lake, "guide.md", "Field Guide", "3.0", prose(13, 150), "2026-09-01")
    run_ingestion(env["cfg"], env["client"])
    run_ingestion(env["cfg"], env["client"])
    got = {m["superseded"] for _, _, m in collection(env).rows.values()
           if m["source"] == "guide.md"}
    assert got == {False}


def test_checking_again_never_calls_the_indexed_original_the_duplicate(
        env: dict[str, Any]) -> None:
    lake = env["lake"]
    seed_corpus(lake)
    run_ingestion(env["cfg"], env["client"])
    for path in (lake / "reports").iterdir():             # forces beta.md to be verified again
        path.unlink()
    (lake / "a-copy-of-beta.md").write_bytes((lake / "beta.md").read_bytes())
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    assert row(report, "beta.md")["outcome"] == "indexed"
    assert row(report, "a-copy-of-beta.md")["outcome"] == "quarantined"
    assert sources(env) == {"alpha.md", "beta.md", "gamma.md"}


def test_a_newer_pdf_version_is_recognised_after_the_old_one_was_archived_with_a_sidecar(
        env: dict[str, Any]) -> None:
    lake = env["lake"]

    def pdf(name: str, version: str, body: str) -> None:
        words = body.split()
        lines = [" ".join(words[i:i + 9]) for i in range(0, len(words), 9)]
        (lake / name).write_bytes(make_pdf([lines]))
        (lake / f"{name}.meta.json").write_text(
            json.dumps({"title": "Field Guide", "version": version}))

    pdf("guide-v1.pdf", "1.0", prose(11, 200))
    run_ingestion(env["cfg"], env["client"])
    pdf("guide-v2.pdf", "2.0", prose(12, 200))
    run_ingestion(env["cfg"], env["client"])
    (lake / "archive" / "guide-v1.pdf.archived.json").write_text("{}")   # written before titles
    pdf("guide-v3.pdf", "3.0", edited(prose(11, 200)))
    run_ingestion(env["cfg"], env["client"])
    assert row(latest_report(lake), "guide-v3.pdf")["outcome"] == "indexed"
