"""Batch B (eval/batch_b) is the ground truth for the verification stage: every planted problem
must be caught by the check the generator says should catch it."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from tests.test_ingest import latest_report, prose, row, write_md

from pipeline.ingest import run_ingestion, source_counts

BATCH = Path(__file__).resolve().parents[2] / "eval" / "batch_b"


def test_every_planted_problem_in_batch_b_is_caught(env: dict[str, Any]) -> None:
    lake = env["lake"]
    # the corpus that is already indexed: a base document and the old Sage Advice edition
    write_md(lake, "base-rules.md", "Base Rules", "1.0", prose(21, 200), "2026-01-01")
    write_md(lake, "sage-advice-compendium-v2-7-2021.md", "Sage Advice Compendium", "2.7",
             prose(22, 200), "2021-12-14")
    run_ingestion(env["cfg"], env["client"])
    assert set(source_counts(env["client"].collections[env["cfg"].collection])) == {
        "base-rules.md", "sage-advice-compendium-v2-7-2021.md"}

    for path in (BATCH / "docs").iterdir():                       # the batch arrives in the lake
        shutil.copy(path, lake / path.name)
    run_ingestion(env["cfg"], env["client"])
    report = latest_report(lake)
    expected = json.loads((BATCH / "expected.json").read_text())
    assert len(expected) >= 10

    for name, want in expected.items():
        got = row(report, name)
        assert got["outcome"].startswith(want["outcome"]), (name, got["outcome"], got["checks"])
        if want.get("check"):
            assert not got["checks"][want["check"]]["passed"], (name, got["checks"])
    # the newer Sage Advice archived the old one, which is kept (superseded) but not deleted
    assert row(report, "sage-advice-compendium-v2-7-2021.md")["outcome"].startswith("archived")
    assert (lake / "archive" / "sage-advice-compendium-v2-7-2021.md").is_file()
    stored = env["client"].collections[env["cfg"].collection]
    flags = {m["source"]: m["superseded"] for _, _, m in stored.rows.values()}
    assert flags["sage-advice-compendium-v2-7-2021.md"] is True
    assert flags["sage-advice-compendium-v2-8.md"] is False
    assert report["documents"] and any(d["warnings"] for d in report["documents"]
                                       if d["source"] == "homebrew-optional-rules.md")
    # six documents quarantined, none of them in the store
    quarantined = {d["source"] for d in report["documents"] if d["outcome"] == "quarantined"}
    assert len(quarantined) == 6
    assert quarantined.isdisjoint(set(source_counts(stored)))
    # re-running ingestion on the same lake embeds nothing
    before = dict(env["calls"])
    run_ingestion(env["cfg"], env["client"])
    assert env["calls"] == before


def test_the_report_checker_agrees_with_the_run(env: dict[str, Any], tmp_path: Path,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    import subprocess
    import sys

    lake = env["lake"]
    write_md(lake, "sage-advice-compendium-v2-7-2021.md", "Sage Advice Compendium", "2.7",
             prose(22, 200), "2021-12-14")
    run_ingestion(env["cfg"], env["client"])
    for path in (BATCH / "docs").iterdir():
        shutil.copy(path, lake / path.name)
    run_ingestion(env["cfg"], env["client"])
    report = sorted((lake / "reports").glob("verification-*.json"))[-1]
    done = subprocess.run([sys.executable, str(BATCH / "check_report.py"), str(report)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout
    assert "DIFFERENT" not in done.stdout and "MISSING" not in done.stdout
