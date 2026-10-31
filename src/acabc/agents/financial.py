"""Agent 02: Financial Pattern Intelligence. Peer comparisons and robust outlier screening. Flags are never fraud labels."""
from __future__ import annotations

from ..models import AgentResult, Role
from ..statistics import robust_z
from .base import Agent

MODEL_VERSION = "mad-robust-z-v1"
REVIEW_Z, WATCH_Z, SMALL_COUNT = 3.5, 1.5, 3


class FinancialPatternIntelligence(Agent):
    agent_id, name = "02", "Financial Pattern Intelligence"

    def run(self, review_z: float = REVIEW_Z, watch_z: float = WATCH_Z, **_: object) -> AgentResult:
        avg = self.call("acabc.aggregate_query", {"metric": "avg_subsidy_per_scheme", "group_by": "state"})
        sch = self.call("acabc.aggregate_query", {"metric": "schemes", "group_by": "state"})
        sub = self.call("acabc.aggregate_query", {"metric": "subsidy_released", "group_by": "state"})
        if not (avg.ok and sch.ok and sub.ok):
            return self.result("unavailable", {}, ["Seed financial aggregates could not be read."])
        schemes = {r["key"]: r["value"] for r in sch.data["rows"]}
        subsidy = {r["key"]: r["value"] for r in sub.data["rows"]}
        usable = [r for r in avg.data["rows"] if r["value"] is not None]
        suppressed = [r["key"] for r in avg.data["rows"] if r["suppressed"] and r["reason"] != "no_schemes_reported"]
        data: dict = {"model_version": MODEL_VERSION, "method": "modified z = 0.6745 * (x - median) / MAD",
                      "thresholds": {"review": review_z, "watch": watch_z}, "unit": "rupees_lakh per scheme",
                      "scope": avg.data["scope"], "reference_date": avg.data["reference_date"]}
        if len(usable) < 4:
            return self.result("unavailable", {**data, "reason": "too_few_comparable_groups"}, ["Fewer than four comparable states."])
        med, mad, z = robust_z([r["value"] for r in usable])
        rows = []
        for r, score in zip(usable, z):
            a = abs(score)
            status = "review" if a >= review_z else "watch" if a >= watch_z else "within_range"
            n = schemes.get(r["key"], r.get("schemes"))
            rows.append({"state": r["key"], "schemes": n, "subsidy_lakh": subsidy.get(r["key"]), "avg_lakh_per_scheme": r["value"],
                         "robust_z": round(score, 3), "status": status,
                         "reliability": "low_count_single_projects" if (n is not None and n < SMALL_COUNT) else "ok",
                         "reasons": [] if status == "within_range" else [
                             f"average {r['value']:.2f} lakh/scheme vs peer median {med:.2f} (MAD {mad:.2f}), robust z {score:.2f}"]})
        rows.sort(key=lambda x: -(x["schemes"] or 0))
        data.update(median=round(med, 4), mad=round(mad, 4), n_groups=len(rows), rows=rows,
                    review=[r["state"] for r in rows if r["status"] == "review"], watch=[r["state"] for r in rows if r["status"] == "watch"],
                    suppressed_for_role=suppressed, no_fraud_label=True)

        val = self.call("acabc.validate_financials", {"group": "nabard_fy2026-27", "metric": "subsidy_released", "unit": "lakh"})
        data["validation"] = val.data if val.ok else {"status": "not_run", "reason": val.error["code"]}

        priv = self.call("acabc.aggregate_query", {"metric": "assistance_mean", "group_by": "state"})
        if priv.ok:
            ok_rows = [r for r in priv.data["rows"] if r["value"] is not None]
            if len(ok_rows) >= 4:
                pm, pmad, pz = robust_z([r["value"] for r in ok_rows])
                data["private_groups"] = {"unit": "rupees", "median": pm, "mad": pmad, "rows": [
                    {"state": r["key"], "n_records": r["n_records"], "mean_assistance": r["value"], "robust_z": round(s, 3),
                     "status": "review" if abs(s) >= review_z else "watch" if abs(s) >= watch_z else "within_range"}
                    for r, s in zip(ok_rows, pz)]}
        caveats = ["A flag means statistically unusual, not wrong. Never a fraud signal; a human reviewer decides.",
                   "States with 1-2 schemes show a single project's size and are low reliability.",
                   "Record-level screening needs the actual ACABC file, comparator groups and reviewer labels (M3)."]
        if self.ctx.actor_role is Role.public:
            caveats.append("Public role: small cells suppressed, so some states are absent from the screen.")
        return self.ok(data, caveats)
