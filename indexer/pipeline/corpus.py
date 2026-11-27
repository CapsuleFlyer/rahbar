"""Which documents are in the data lake right now.

The lake is the corpus volume (`/corpus` in the Job). Its root holds the ACTIVE documents plus
`_index.json` (written by corpus/fetch.py) when there is one. Three folders sit beside them:

    quarantine/   documents that failed verification, each with a <name>.reason.json
    archive/      superseded versions, each with a <name>.archived.json (restorable)
    reports/      one verification report per run

A document dropped into the root is ingested on the next run even if `_index.json` does not
list it: that is how a new batch arrives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOC_SUFFIXES = {".pdf", ".md", ".html", ".htm", ".txt"}
# files that belong beside documents (metadata, config, operating-system litter): never reported
IGNORED_SUFFIXES = {".json", ".yaml", ".yml"}
IGNORED_NAMES = {"thumbs.db", "desktop.ini"}


@dataclass(frozen=True)
class Candidate:
    path: Path
    doc_version: str
    superseded: bool
    entry: dict[str, Any] | None = None        # the _index.json row, when there is one

    @property
    def source(self) -> str:
        return self.path.name


def front_matter(path: Path) -> dict[str, str]:
    """Read `key: value` lines between leading '---' markers (used by eval/fixtures)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def index_entries(corpus_dir: str) -> dict[str, dict[str, Any]]:
    """The `_index.json` rows by file name, including files that have since left the root."""
    index = Path(corpus_dir) / "_index.json"
    if not index.exists():
        return {}
    return {str(e["file"]): e for e in json.loads(index.read_text(encoding="utf-8"))}


def discover_entries(corpus_dir: str) -> list[Candidate]:
    """Every active document: the ones `_index.json` lists (and that still exist), then any
    other document file in the root, with its metadata from front matter."""
    root = Path(corpus_dir)
    found: list[Candidate] = []
    listed: set[str] = set()
    index = root / "_index.json"
    if index.exists():
        for entry in json.loads(index.read_text(encoding="utf-8")):
            listed.add(str(entry["file"]))
            path = root / entry["file"]
            if path.is_file():                     # moved to quarantine/archive: not active
                found.append(Candidate(path, str(entry.get("doc_version", "unknown")),
                                       bool(entry.get("superseded", False)), entry))
    for path in sorted(root.glob("*")):
        if (not path.is_file() or path.suffix.lower() not in DOC_SUFFIXES
                or path.name in listed or path.name.lower().startswith("readme")):
            continue
        meta = front_matter(path) if path.suffix.lower() == ".md" else {}
        version = meta.get("doc_version") or meta.get("version") or "unknown"
        found.append(Candidate(path, version, meta.get("superseded", "false").lower() == "true"))
    return found


def discover_unsupported(corpus_dir: str) -> list[Path]:
    """Files in the lake root that look like documents but cannot be read (a .docx, say). They
    are verified like any other arrival, so they are quarantined and reported, never skipped."""
    root = Path(corpus_dir)
    listed = {c.path.name for c in discover_entries(corpus_dir)}
    found = []
    for path in sorted(root.glob("*")):
        name = path.name.lower()
        if (path.is_file() and path.name not in listed and path.suffix.lower() not in DOC_SUFFIXES
                and path.suffix.lower() not in IGNORED_SUFFIXES and name not in IGNORED_NAMES
                and not name.startswith((".", "readme"))):
            found.append(path)
    return found


def discover(corpus_dir: str) -> list[tuple[Path, str, bool]]:
    """(path, doc_version, superseded) for every active document."""
    return [(c.path, c.doc_version, c.superseded) for c in discover_entries(corpus_dir)]
