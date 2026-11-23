#!/usr/bin/env python3
"""Print everything that produced one answer, from its trace record (RAGOps D2).

    python scripts/trace_show.py <trace_id> [FILE ...]        default files: traces/*.jsonl
    make trace ID=<trace_id>                                   reads the volume on the cluster
    ... | python scripts/trace_show.py <trace_id> -             reads stdin (kubectl logs, ...)

The trace id is the `request_id` of the reply (shown as `trace:` by `make ask`). A unique
prefix is enough. `--json` prints the raw record. Standard library only.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from typing import Any, Iterable

RULE = "-" * 78


def read_lines(paths: list[str]) -> Iterable[str]:
    for path in paths:
        if path == "-":
            yield from sys.stdin
            continue
        with open(path, encoding="utf-8") as handle:
            yield from handle


def find(trace_id: str, lines: Iterable[str]) -> list[dict[str, Any]]:
    """Latest record for each distinct trace id that starts with `trace_id`."""
    found: dict[str, dict[str, Any]] = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (isinstance(record, dict) and record.get("msg") == "trace"
                and str(record.get("trace_id", "")).startswith(trace_id)):
            found[str(record["trace_id"])] = record
    return list(found.values())


def _kv(**items: Any) -> str:
    return "  ".join(f"{k}={v}" for k, v in items.items() if v is not None)


def render(r: dict[str, Any]) -> str:
    out: list[str] = []
    add = out.append
    emb, col = r.get("embedding") or {}, r.get("collection") or {}
    params, cache = r.get("params") or {}, r.get("cache") or {}
    add(f"TRACE {r.get('trace_id')}   {r.get('ts')}   outcome={r.get('outcome')}")
    add(RULE)
    add(f"QUESTION   {r.get('query')}")
    add(f"REWRITTEN  {r.get('rewritten_query') or '(none: this pipeline does not rewrite queries)'}")
    add("")
    add("PIPELINE")
    add("  " + _kv(retriever=r.get("retriever"), embedding=emb.get("model"),
                   dimension=emb.get("dimension")))
    add("  " + _kv(collection=col.get("name"), index_id=col.get("index_id"),
                   built_at=col.get("built_at")))
    add(f"  filters={json.dumps((r.get('filters') or {}).get('where'))}  "
        + _kv(top_k=params.get("top_k"), relevance_floor=params.get("relevance_floor")))
    add(f"  cache={cache.get('result')}"
        + (f" ({cache['reason']})" if cache.get("reason") else "")
        + (" · stored" if cache.get("stored") else ""))
    add("")
    order = list((r.get("rerank") or {}).get("order") or [])
    in_prompt = set(order)
    retrieved = r.get("retrieved") or []
    add(f"RETRIEVED ({len(retrieved)}), best first. [P] = went into the prompt")
    for i, c in enumerate(retrieved, 1):
        mark = "P" if c.get("chunk_id") in in_prompt else " "
        ver = f" v{c['doc_version']}" if c.get("doc_version") else ""
        add(f"  {i} [{mark}] {c.get('score'):.3f}  {c.get('doc_id')}{ver}"
            f"  {c.get('section')}  p.{c.get('page')}  ({c.get('chunk_id')})")
    add(f"  reranker: {'applied' if (r.get('rerank') or {}).get('applied') else 'none'}"
        f"; order sent to the model: {', '.join(order) if order else '(none)'}")
    add("")
    add("GUARDRAILS")
    actions = r.get("guardrails") or []
    if not actions:
        add("  no action: nothing flagged")
    for g in actions:
        where = g.get("target") + (f" {g['chunk_id']}" if g.get("chunk_id") else "")
        add(f"  {g.get('rail')}: {g.get('action')} on {where}  patterns={g.get('patterns')}")
    add("")
    prompt = r.get("prompt")
    if prompt:
        add(f"PROMPT   sha256={prompt.get('hash')}   (the exact messages sent to the model)")
        for message in prompt.get("messages") or []:
            add(f"--- {message.get('role')} " + "-" * 60)
            add(str(message.get("content")))
        add("-" * 78)
    else:
        why = {"cache_hit": "answered from the semantic cache, so no prompt was built",
               "abstained:floor": "nothing cleared the relevance floor, so no model was called"
               }.get(str(r.get("outcome")), "the request ended before a prompt was built")
        add(f"PROMPT   none: {why}")
    add("")
    gen = r.get("generation")
    if gen:
        add("MODEL    " + _kv(provider=gen.get("provider"), model=gen.get("model"),
                              temperature=gen.get("temperature"),
                              tokens_in=gen.get("tokens_in"), tokens_out=gen.get("tokens_out")))
    resp = r.get("response") or {}
    add(f"RESPONSE  answered_from_context={resp.get('answered_from_context')}  "
        f"confidence={resp.get('confidence')}  fallback={resp.get('fallback')}  "
        f"citations_dropped={resp.get('citations_dropped')}")
    add(f"  {resp.get('answer')}")
    for c in resp.get("citations") or []:
        add(f"  cites: {c.get('source')} › {c.get('section')} p.{c.get('page')}")
    if resp.get("reasoning"):
        add(f"  model reasoning (never shown to users): {resp['reasoning']}")
    add("")
    lat = r.get("latency_ms") or {}
    add("LATENCY  " + "  ".join(f"{k}={v}ms" for k, v in lat.items()))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("trace_id")
    ap.add_argument("files", nargs="*", help="trace files, or - for stdin")
    ap.add_argument("--json", action="store_true", help="print the raw record")
    args = ap.parse_args(argv)
    files = args.files or sorted(glob.glob("traces/*.jsonl"))
    if not files:
        print("no trace files: pass FILE(s), '-' for stdin, or put *.jsonl under traces/")
        return 2
    matches = find(args.trace_id, read_lines(files))
    if not matches:
        print(f"no trace record starts with {args.trace_id!r}")
        return 1
    if len(matches) > 1:
        print(f"{args.trace_id!r} matches {len(matches)} traces; use a longer prefix:")
        for m in matches:
            print(f"  {m['trace_id']}  {m.get('ts')}  {str(m.get('query'))[:60]}")
        return 2
    print(json.dumps(matches[0], indent=2, ensure_ascii=False) if args.json else render(matches[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
