"""Agent 01: Beneficiary Intelligence. Audited segments from approved fields; SQL-style grouping, clustering only where stable."""
from __future__ import annotations

from ..models import AgentResult
from .base import Agent

TIERS = (("thin", 0, 100), ("small", 100, 1000), ("medium", 1000, 5000), ("large", 5000, 10**9))


class BeneficiaryIntelligence(Agent):
    agent_id, name = "01", "Beneficiary Intelligence"

    def run(self, **_: object) -> AgentResult:
        data: dict = {}
        bm = self.call("gov.get_benchmark", {"benchmark_id": "mis_2026-10-26"})
        if bm.ok:
            d = bm.data["benchmarks"][0]["detail"]
            eras = {}
            for key in ("era_2002_2017", "era_2018_onward_mis"):
                e = d[key]
                eras[key] = {**{k: e[k] for k in ("trained", "ventures")},
                             "ventures_per_trained": round(e["ventures"] / e["trained"], 4),
                             "label": "ratio of cumulative era totals, not a matched-cohort conversion rate"}
            eras["mis_era_pipeline"] = {k: d["era_2018_onward_mis"][k] for k in ("registered", "approved_by_manage", "subsidy_cases")}
            data["eras"] = eras

        tr = self.call("acabc.aggregate_query", {"metric": "trained", "group_by": "state"})
        if tr.ok:
            tiers: dict[str, list[str]] = {t[0]: [] for t in TIERS}
            suppressed = []
            for r in tr.data["rows"]:
                if r["suppressed"]:
                    suppressed.append(r["key"])
                    continue
                for name, lo, hi in TIERS:
                    if lo <= r["value"] < hi:
                        tiers[name].append(r["key"])
            data["state_size_tiers"] = {
                "basis": "cumulative candidates trained (MANAGE, 1 Oct 2026)",
                "bands": {n: f"{lo} to {hi - 1}" if hi < 10**9 else f"{lo}+" for n, lo, hi in TIERS},
                "counts": {n: len(v) for n, v in tiers.items()}, "members": tiers, "suppressed_for_role": suppressed}

        seg = self.call("acabc.aggregate_query", {"metric": "records", "group_by": "enterprise_type"})
        data["enterprise_segments"] = ({"available": True, "rows": seg.data["rows"]} if seg.ok else {
            "available": False, "reason": seg.error["code"],
            "note": "Enterprise-type and beneficiary-profile segments need the record-level file (M0) with a mapped enterprise_type field."})
        return self.ok(data, ["Segments describe administrative counts; they do not rank or judge states."])
