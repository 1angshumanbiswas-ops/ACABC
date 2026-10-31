"""Append-only, hash-chained audit log. Tampering with any earlier entry breaks verify()."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


class AuditLog:
    GENESIS = "0" * 64

    def __init__(self, path: str | Path | None = None) -> None:
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self._path = Path(path) if path else None

    def append(self, **fields: Any) -> dict:
        with self._lock:
            prev = self._entries[-1]["hash"] if self._entries else self.GENESIS
            entry = {"seq": len(self._entries), "ts": datetime.now(timezone.utc).isoformat(), **fields, "prev": prev}
            entry["hash"] = hashlib.sha256((prev + _canon(entry)).encode()).hexdigest()
            self._entries.append(entry)
            if self._path:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(_canon(entry) + "\n")
            return entry

    def entries(self, trace_id: str | None = None) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._entries if trace_id is None or e.get("trace_id") == trace_id]

    def verify(self) -> bool:
        prev = self.GENESIS
        with self._lock:
            for e in self._entries:
                body = {k: v for k, v in e.items() if k != "hash"}
                if body["prev"] != prev or hashlib.sha256((prev + _canon(body)).encode()).hexdigest() != e["hash"]:
                    return False
                prev = e["hash"]
        return True
