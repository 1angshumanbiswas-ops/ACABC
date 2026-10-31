"""Application state shared by the tool server, agents and API."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .audit import AuditLog
from .ingest import PrivateStore
from .sources import SEED_VERSION, Seed, load_seed

DISPOSITIONS = ("no_action", "needs_clarification", "escalate_to_programme_official")  # deliberately no "fraud"


class ReviewStore:
    """anomaly_review: cases carry a score and a reviewer decision. No fraud label exists."""

    def __init__(self, audit: AuditLog) -> None:
        self._cases: dict[str, dict] = {}
        self._audit = audit
        self._lock = threading.Lock()

    def open_case(self, *, trace_id: str, model_ver: str, group: str, score: float, reasons: list[str]) -> dict:
        case = {"case_id": uuid.uuid4().hex[:12], "trace_id": trace_id, "model_ver": model_ver, "group": group,
                "score": round(score, 3), "reasons": reasons, "reviewer": None, "decision": None, "decided_at": None}
        with self._lock:
            self._cases[case["case_id"]] = case
        self._audit.append(trace_id=trace_id, event="anomaly_case_opened", case_id=case["case_id"], group=group,
                           score=case["score"], model_ver=model_ver)
        return dict(case)

    def disposition(self, case_id: str, reviewer: str, decision: str, note: str = "") -> dict:
        if decision not in DISPOSITIONS:
            raise ValueError(f"decision must be one of {DISPOSITIONS}")
        with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise KeyError(case_id)
            if case["decision"] is not None:
                raise PermissionError("case already dispositioned; audit entries are immutable")
            case.update(reviewer=reviewer, decision=decision, decided_at=datetime.now(timezone.utc).isoformat())
            snapshot = dict(case)
        self._audit.append(trace_id=case["trace_id"], event="anomaly_case_dispositioned", case_id=case_id,
                           reviewer=reviewer, decision=decision, note=note[:500])
        return snapshot

    def get(self, case_id: str) -> dict | None:
        with self._lock:
            c = self._cases.get(case_id)
            return dict(c) if c else None

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self._cases.values()]


class ReportStore:
    """report_artifact: reproducible exports keyed by trace_id with an artifact hash."""

    def __init__(self) -> None:
        self._reports: dict[str, dict] = {}

    def put(self, trace_id: str, report: dict) -> dict:
        body = json.dumps(report, sort_keys=True, default=str)
        stored = {"trace_id": trace_id, "generated_at": datetime.now(timezone.utc).isoformat(),
                  "artifact_hash": hashlib.sha256(body.encode()).hexdigest(), "report": report}
        self._reports[trace_id] = stored
        return stored

    def get(self, trace_id: str) -> dict | None:
        return self._reports.get(trace_id)


@dataclass
class AppState:
    seed: Seed
    audit: AuditLog
    reviews: ReviewStore
    reports: ReportStore
    dataset_version: str = SEED_VERSION
    private: PrivateStore | None = None
    public_min_cell: int = 10
    ratio_min_trained: int = 100
    extras: dict = field(default_factory=dict)

    @property
    def active_dataset_version(self) -> str:
        return self.private.dataset_version if self.private else self.dataset_version


def build_state(private: PrivateStore | None = None, audit_path: str | None = None) -> AppState:
    audit = AuditLog(audit_path)
    return AppState(seed=load_seed(), audit=audit, reviews=ReviewStore(audit), reports=ReportStore(), private=private)
