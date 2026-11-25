"""The indexer Job's entry point. It runs once and exits (section 4.2).

    python -m pipeline.run --dummy    # week 1: three fake chunks, no model needed
    python -m pipeline.run            # the real pipeline: extract, clean, chunk, embed, store

Exit code 0 means the index was written; anything else fails the Job, and
Kubernetes retries it up to the Job's backoffLimit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import IndexerSettings, get_settings
from .corpus import DOC_SUFFIXES, discover  # noqa: F401  (re-exported: tests and tools import them)
from .corpus import front_matter as _front_matter  # noqa: F401


def log(msg: str, **fields: object) -> None:
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                      "logger": "rahbar.indexer", "msg": msg, **fields}), flush=True)


def wait_for_corpus(settings: IndexerSettings) -> None:
    """Poll until the corpus directory holds documents (the Job may start before the
    corpus PVC is loaded), for at most CORPUS_WAIT_SECONDS."""
    deadline = time.monotonic() + settings.corpus_wait_seconds
    while True:
        if Path(settings.corpus_dir).is_dir() and discover(settings.corpus_dir):
            return
        if time.monotonic() >= deadline:
            raise SystemExit(f"no documents found in {settings.corpus_dir}")
        log("waiting for corpus", corpus_dir=settings.corpus_dir)
        time.sleep(5)


def wait_for_chroma(settings: IndexerSettings, client: Any | None = None) -> Any:
    """Retry the heartbeat until Chroma answers, for at most CHROMA_WAIT_SECONDS."""
    from .store import get_client

    deadline = time.monotonic() + settings.chroma_wait_seconds
    while True:
        try:
            client = client or get_client(settings)
            client.heartbeat()
            return client
        except Exception as exc:
            if time.monotonic() >= deadline:
                raise SystemExit(f"Chroma at {settings.chroma_host}:{settings.chroma_port} "
                                 f"did not answer: {exc}") from exc
            log("waiting for chroma", error=str(exc)[:120])
            time.sleep(3)


def run_pipeline(settings: IndexerSettings, client: Any | None = None) -> int:
    """Verify, chunk, embed and store the corpus, doing only the work that changed (ingest.py)."""
    from .ingest import run_ingestion

    wait_for_corpus(settings)
    client = wait_for_chroma(settings, client)
    return run_ingestion(settings, client)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the RAHBAR index, then exit.")
    parser.add_argument("--dummy", action="store_true", help="write three fake chunks")
    args = parser.parse_args()
    settings = get_settings()
    log("indexer starting", dummy=args.dummy, embed_model=settings.embed_model,
        collection=settings.collection, chroma=f"{settings.chroma_host}:{settings.chroma_port}",
        pod=os.environ.get("HOSTNAME", "-"))
    started = time.perf_counter()
    try:
        if args.dummy:
            from .dummy import write_dummy_index
            from .store import get_client

            count = write_dummy_index(settings, get_client(settings))
        else:
            count = run_pipeline(settings)
    except NotImplementedError as exc:
        log("indexer stage not implemented yet", error=str(exc))
        return 2
    log("indexer finished", chunks=count, seconds=round(time.perf_counter() - started, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
