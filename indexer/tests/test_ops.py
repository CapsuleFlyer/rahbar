from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from tests.test_ingest import prose, write_md

from pipeline import ops
from pipeline.config import get_settings
from pipeline.lake import Lake


def test_list_and_rollback_move_files_and_say_what_happens_next(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    lake = tmp_path
    write_md(lake, "guide-v1.md", "Field Guide", "1.0", prose(1, 60), "2026-01-01")
    write_md(lake, "guide-v2.md", "Field Guide", "2.0", prose(2, 60), "2026-06-01")
    keeper = Lake(str(lake))
    keeper.prepare()
    keeper.archive_file(lake / "guide-v1.md", "guide-v2.md", "1.0")
    (lake / "quarantine" / "bad.md").write_text("x")
    (lake / "quarantine" / "bad.md.reason.json").write_text(
        json.dumps({"failed_checks": {"quality": "garbled"}}))
    cfg = replace(get_settings(), corpus_dir=str(lake))
    monkeypatch.setattr(ops, "get_settings", lambda: cfg)

    assert ops.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "guide-v2.md" in out and "superseded by guide-v2.md" in out and "quality: garbled" in out

    assert ops.main(["rollback", "guide-v1.md"]) == 0
    assert "restored guide-v1.md, archived guide-v2.md" in capsys.readouterr().out
    assert (lake / "guide-v1.md").is_file() and (lake / "archive" / "guide-v2.md").is_file()
    with pytest.raises(FileNotFoundError):
        ops.main(["rollback", "nothing.md"])


def test_delete_removes_the_file_and_says_to_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    write_md(tmp_path, "gone.md", "Gone", "1.0", prose(3, 60), "2026-01-01")
    (tmp_path / "gone.md.meta.json").write_text("{}")
    monkeypatch.setattr(ops, "get_settings", lambda: replace(get_settings(), corpus_dir=str(tmp_path)))
    assert ops.main(["delete", "gone.md"]) == 0
    assert not (tmp_path / "gone.md").exists() and not (tmp_path / "gone.md.meta.json").exists()
    assert "make ingest" in capsys.readouterr().out
    assert ops.main(["delete", "gone.md"]) == 1
