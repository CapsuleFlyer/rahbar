"""Operator commands for the data lake (RAGOps A2). Run as: python -m pipeline.ops <command>

  list                      what is active, archived and quarantined in the lake
  counts [--source NAME]    chunks per document in the vector store (the proof of "no orphans")
  rollback NAME             bring an archived version back and archive the version that
                            superseded it; the next ingestion run flips the chunk flags
  delete NAME               remove a document from the lake; the next ingestion run deletes
                            its chunks, leaving no orphans (check with `counts --source NAME`)

Nothing here writes to Chroma. `rollback` only moves files, and the ingestion Job (the single
writer) applies the change to the vector store on its next run.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from .config import IndexerSettings, get_settings
from .corpus import discover_entries
from .lake import Lake


def cmd_list(settings: IndexerSettings, _args: argparse.Namespace) -> int:
    lake = Lake(settings.corpus_dir)
    print(f"ACTIVE ({settings.corpus_dir})")
    for c in discover_entries(settings.corpus_dir):
        print(f"  {c.source:<52} v{c.doc_version}{'  (superseded flag)' if c.superseded else ''}")
    print("ARCHIVE (restorable with: rollback NAME)")
    for name in sorted(lake.archived_names()):
        info = lake.archived_info(name)
        print(f"  {name:<52} superseded by {info.get('superseded_by', '?')}  "
              f"archived {info.get('archived_at', '?')}")
    print("QUARANTINE")
    for name in sorted(lake.quarantined_names()):
        side = lake.quarantine / (name + ".reason.json")
        failed = json.loads(side.read_text(encoding="utf-8")).get("failed_checks", {})
        print(f"  {name:<52} {'; '.join(f'{k}: {v}' for k, v in failed.items())[:160]}")
    return 0


def cmd_counts(settings: IndexerSettings, args: argparse.Namespace) -> int:
    from .ingest import source_states
    from .store import _get_existing, get_client

    collection = _get_existing(get_client(settings), settings.collection)
    if collection is None:
        print(f"collection {settings.collection!r} does not exist")
        return 1
    states: dict[str, Any] = source_states(collection)
    print(f"collection {settings.collection}: {collection.count()} chunks")
    shown = 0
    for source, st in sorted(states.items()):
        if args.source and source != args.source:
            continue
        shown += 1
        print(f"  {source:<52} {st.count:>6} chunks  versions={sorted(st.versions)}  "
              f"superseded={sorted(st.superseded)}")
    if args.source and not shown:
        print(f"  {args.source}: 0 chunks (no orphans: nothing is stored for it)")
    return 0


def cmd_rollback(settings: IndexerSettings, args: argparse.Namespace) -> int:
    result = Lake(settings.corpus_dir).restore(args.name)
    print(f"restored {result['restored']}"
          + (f", archived {result['archived']}" if result["archived"] else ""))
    print("next: run the ingestion Job (make ingest); it flips the chunk flags, embedding nothing")
    return 0


def cmd_delete(settings: IndexerSettings, args: argparse.Namespace) -> int:
    from pathlib import Path

    root = Path(settings.corpus_dir)
    target = root / args.name
    if not target.is_file():
        print(f"{args.name} is not an active document in {root}")
        return 1
    target.unlink()
    (root / (args.name + ".meta.json")).unlink(missing_ok=True)
    print(f"deleted {args.name}; run the ingestion Job (make ingest) to prune its chunks")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    counts = sub.add_parser("counts")
    counts.add_argument("--source")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("name")
    delete = sub.add_parser("delete")
    delete.add_argument("name")
    args = ap.parse_args(argv)
    settings = get_settings()
    handler = {"list": cmd_list, "counts": cmd_counts, "rollback": cmd_rollback,
               "delete": cmd_delete}[args.command]
    return handler(settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
