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

    def archive_file(self, path: Path, superseded_by: str, doc_version: str,
                     title: str = "") -> str | None:
        if not self.writable:
            return None
        target = self.archive / path.name
        if target.exists():
            target.unlink()
        shutil.move(str(path), str(target))
        Path(str(target) + ".archived.json").write_text(
            json.dumps({"file": path.name, "archived_at": _now(), "doc_version": doc_version,
                        "title": title, "superseded_by": superseded_by}, indent=2),
            encoding="utf-8")
        return str(target)

    def archived_names(self) -> set[str]:
        if not self.archive.is_dir():
            return set()
        return {p.name for p in self.archive.iterdir()
                if p.is_file() and not p.name.endswith(".archived.json")}

    def quarantine_records(self) -> list[tuple[str, Path, dict[str, Any]]]:
        """Open quarantine records as (document name, quarantined copy, record). A second failure
        of the same name is stored as <name>.1, so the name comes from the record itself."""
        records: list[tuple[str, Path, dict[str, Any]]] = []
        if not self.quarantine.is_dir():
            return records
        for sidecar in sorted(self.quarantine.glob("*.reason.json")):
            copy = sidecar.with_name(sidecar.name.removesuffix(".reason.json"))
            try:
                data = dict(json.loads(sidecar.read_text(encoding="utf-8")))
            except ValueError:
                data = {}
            records.append((str(data.get("file") or copy.name), copy, data))
        return records

    def quarantined_names(self) -> set[str]:
        return {name for name, _, _ in self.quarantine_records()}

    def resolve_quarantine(self, name: str, why: str) -> int:
        """Close a document's open records (it passed, or was deleted). The bad copy and the
        record are kept as <copy>.resolved.json, but no longer protect the old chunks."""
        if not self.writable:
            return 0
        closed = 0
        for found, copy, data in self.quarantine_records():
            if found != name:
                continue
            data.update({"resolved_at": _now(), "resolution": why})
            Path(str(copy) + ".resolved.json").write_text(json.dumps(data, indent=2),
                                                          encoding="utf-8")
            Path(str(copy) + ".reason.json").unlink()
            closed += 1
        return closed

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

    def verified_rows(self, config_sig: str, wanted: dict[str, str]) -> dict[str, dict[str, Any]]:
        """For each wanted document (name -> file SHA-256), the newest earlier report row in which
        that exact file passed quality, completeness and uniqueness under the same settings."""
        found: dict[str, dict[str, Any]] = {}
        if not self.reports.is_dir():
            return found
        for path in sorted(self.reports.glob("verification-*.json"), reverse=True):
            if len(found) == len(wanted):
                break
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
                if report.get("config_sig") != config_sig:
                    continue
                for row in report["documents"]:
                    name = row["source"]
                    if name in found or wanted.get(name) != row["sha256"]:
                        continue
                    if all(row["checks"].get(n, {}).get("passed")
                           for n in ("quality", "completeness", "uniqueness")):
                        found[name] = {**row, "run_id": row.get("verified_in") or report["run_id"]}
            except (ValueError, KeyError, TypeError, AttributeError):
                continue                       # a damaged report is simply not carried forward
        return found

    def write_report(self, run_id: str, report: dict[str, Any], markdown: str) -> list[str]:
        if not self.writable:
            return []
        name, n = f"verification-{run_id}", 1
        while (self.reports / f"{name}.json").exists():       # two runs within one second
            n += 1
            name = f"verification-{run_id}_{n}"               # "_" sorts after the first one
        written = []
        for suffix, body in ((".json", json.dumps(report, indent=2)), (".md", markdown)):
            path = self.reports / f"{name}{suffix}"
            path.write_text(body, encoding="utf-8")
            written.append(str(path))
        return written
