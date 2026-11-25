"""The data lake folders (RAGOps A1, A2): quarantine, archive and reports on the corpus volume.

Moving a file is a rename inside one volume, so it is atomic and survives pod restarts. Every
move leaves a small JSON sidecar saying why, so nothing is lost silently and an archived
version can be restored.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Lake:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.quarantine = self.root / "quarantine"
        self.archive = self.root / "archive"
        self.reports = self.root / "reports"
        self.writable = False

    def prepare(self) -> bool:
        """Create the folders. False when the volume is read-only: ingestion still runs, but
        failing documents cannot be moved, so the run says so instead of pretending."""
        try:
            for folder in (self.quarantine, self.archive, self.reports):
                folder.mkdir(parents=True, exist_ok=True)
            self.writable = True
        except OSError:
            self.writable = False
        return self.writable

    @staticmethod
    def _free(path: Path) -> Path:
        if not path.exists():
            return path
        n = 1
        while path.with_name(f"{path.name}.{n}").exists():
            n += 1
        return path.with_name(f"{path.name}.{n}")

    def quarantine_file(self, path: Path, reasons: dict[str, str]) -> str | None:
        if not self.writable:
            return None
        target = self._free(self.quarantine / path.name)
        shutil.move(str(path), str(target))
        Path(str(target) + ".reason.json").write_text(
            json.dumps({"file": path.name, "quarantined_at": _now(), "failed_checks": reasons},
                       indent=2), encoding="utf-8")
        return str(target)

    def archive_file(self, path: Path, superseded_by: str, doc_version: str) -> str | None:
        if not self.writable:
            return None
        target = self.archive / path.name
        if target.exists():
            target.unlink()
        shutil.move(str(path), str(target))
        Path(str(target) + ".archived.json").write_text(
            json.dumps({"file": path.name, "archived_at": _now(), "doc_version": doc_version,
                        "superseded_by": superseded_by}, indent=2), encoding="utf-8")
        return str(target)

    def archived_names(self) -> set[str]:
        if not self.archive.is_dir():
            return set()
        return {p.name for p in self.archive.iterdir()
                if p.is_file() and not p.name.endswith(".archived.json")}

    def quarantined_names(self) -> set[str]:
        if not self.quarantine.is_dir():
            return set()
        return {p.name.split(".reason.json")[0] for p in self.quarantine.glob("*.reason.json")}

    def archived_info(self, name: str) -> dict[str, Any]:
        sidecar = self.archive / (name + ".archived.json")
        return dict(json.loads(sidecar.read_text(encoding="utf-8"))) if sidecar.exists() else {}

    def restore(self, name: str) -> dict[str, Any]:
        """Roll back: put an archived version back among the active documents, and archive the
        version that superseded it. The vector store is untouched here: the next ingestion run
        flips the chunks' `superseded` metadata, so only the Job ever writes to Chroma."""
        if not self.writable and not self.prepare():
            raise PermissionError(f"{self.root} is not writable: cannot restore")
        source = self.archive / name
        if not source.is_file():
            raise FileNotFoundError(f"{name} is not in {self.archive}")
        info = self.archived_info(name)
        shutil.move(str(source), str(self.root / name))
        (self.archive / (name + ".archived.json")).unlink(missing_ok=True)
        newer = info.get("superseded_by")
        archived_newer = None
        if newer and (self.root / newer).is_file():
            archived_newer = self.archive_file(self.root / newer, superseded_by=name,
                                               doc_version="rolled back")
        return {"restored": name, "archived": newer if archived_newer else None}

    def write_report(self, run_id: str, report: dict[str, Any], markdown: str) -> list[str]:
        if not self.writable:
            return []
        written = []
        for suffix, body in ((".json", json.dumps(report, indent=2)), (".md", markdown)):
            path = self.reports / f"verification-{run_id}{suffix}"
            path.write_text(body, encoding="utf-8")
            written.append(str(path))
        return written
