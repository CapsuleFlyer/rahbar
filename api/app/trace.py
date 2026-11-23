"""Trace records (RAGOps D1, F4): one JSON line per query, with everything needed to
explain the answer afterwards.

A record goes to two places, as the same line:
  * stdout, so `kubectl logs` shows it (a pod's own filesystem is ephemeral);
  * `<TRACE_DIR>/traces-<pod>.jsonl`, on a PersistentVolumeClaim, so the report scripts and
    `scripts/trace_show.py` can read the history after pods restart. Each pod writes its
    own file, so three replicas never interleave half-written lines.

Writing a trace must never break an answer: file errors are logged once and swallowed.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("rahbar.trace")


class TraceWriter:
    def __init__(self, directory: str = "", pod: str = "api") -> None:
        self.path: Path | None = None
        self._lock = threading.Lock()
        self._warned = False
        if directory:
            self.path = Path(directory) / f"traces-{pod or 'api'}.jsonl"
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._warn(exc)

    def _warn(self, exc: Exception) -> None:
        if not self._warned:
            self._warned = True
            log.warning("trace file not writable; traces go to stdout only",
                        extra={"error": f"{type(exc).__name__}: {exc}"[:200],
                               "trace_file": str(self.path)})

    def line(self, record: dict[str, Any]) -> str:
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        entry = {"ts": stamp.replace("+00:00", "Z"), "level": "INFO",
                 "logger": "rahbar.trace", "msg": "trace", **record}
        return json.dumps(entry, default=str, ensure_ascii=False)

    def write(self, record: dict[str, Any]) -> None:
        line = self.line(record)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
        if self.path is None:
            return
        try:
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            self._warn(exc)
