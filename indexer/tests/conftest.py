"""Shared fixtures for the ingestion tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pipeline.config import IndexerSettings, get_settings
from tests.fakes import FakeClient
from tests.test_ingest import fake_embed


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls = {"texts": 0, "batches": 0}

    def counting_embed(texts: list[str], settings: IndexerSettings) -> list[list[float]]:
        calls["batches"] += 1
        calls["texts"] += len(texts)
        return fake_embed(texts, settings)

    monkeypatch.setattr("pipeline.embed.embed", counting_embed)
    lake = tmp_path / "lake"
    lake.mkdir()
    cfg = replace(get_settings(), corpus_dir=str(lake), chunk_size=60, chunk_overlap=10,
                  embed_model="nomic-embed-text", corpus_wait_seconds=0)
    return {"lake": lake, "cfg": cfg, "client": FakeClient(), "calls": calls}
