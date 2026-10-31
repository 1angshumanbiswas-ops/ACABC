"""Agent 03: Geo Intelligence. Concentration, coverage diagnostics and interpretable clusters. State level only unless a district field is ingested."""
from __future__ import annotations

from ..models import AgentResult
from ..statistics import cluster_states
from .base import Agent


class GeoIntelligence(Agent):
    agent_id, name = "03", "Geo Intelligence"

    def run(self, k: int = 3, **_: object) -> AgentResult:
        q = lambda m: self.call("acabc.aggregate_query", {"metric": m, "group_by": "state"})  # noqa: E731
        ven, rat, sch, sub = q("ventures"), q("ventures_per_trained"), q("schemes"), q("subsidy_released")
        if not (ven.ok and rat.ok and sch.ok and sub.ok):
            return self.result("unavailable", {}, ["Seed geographic aggregates could not be read."])
        tot_v, tot_s, tot_sub = ven.data["national_total"], sch.data["national_total"], sub.data["national_total"]
        ranked = sorted((r for r in ven.data["rows"] if r["value"] is not None), key=lambda r: -r["value"])
        top3 = ranked[:3]
        concentration = {"basis": "cumulative ventures, MANAGE 1 Oct 2026", "top3": [{"state": r["key"], "ventures": r["value"]} for r in top3],
                         "top3_share_of_national": round(sum(r["value"] for r in top3) / tot_v, 4), "national_total": tot_v,
                         "note": "Concentration is a measurement, not evidence of unmet demand, discrimination or failure."}
        sch_rows = [r for r in sch.data["rows"] if r["value"]]
        lead = max(sch_rows, key=lambda r: r["value"]) if sch_rows else None
        sub_by = {r["key"]: r["value"] for r in sub.data["rows"]}
        fy = {"basis": "NABARD FY 2026-27 to 30 Sep 2026", "states_with_schemes": len(sch_rows), "states_listed": len(sch.data["rows"]),
              "national_schemes": tot_s, "national_subsidy_lakh": tot_sub}
        if lead:
            fy["lead_state"] = {"state": lead["key"], "schemes": lead["value"], "share_of_schemes": round(lead["value"] / tot_s, 4),
                                "subsidy_lakh": sub_by[lead["key"]], "share_of_subsidy": round(sub_by[lead["key"]] / tot_sub, 4)}
        thin = [r["key"] for r in rat.data["rows"] if r["suppressed"]]
        ratios = [r for r in rat.data["rows"] if r["value"] is not None]
        spread = {"min": min(ratios, key=lambda r: r["value"]) if ratios else None, "max": max(ratios, key=lambda r: r["value"]) if ratios else None}
        coverage = {"thin_states_ratio_suppressed": thin, "n_thin": len(thin), "n_states": len(rat.data["rows"]),
                    "zero_venture_states": [r["key"] for r in ven.data["rows"] if r["value"] == 0],
                    "ratio_spread": {k_: ({"state": v["key"], "ratio": v["value"]} if v else None) for k_, v in spread.items()},
                    "ratio_label": "ratio of cumulative totals, not a success or conversion rate",
                    "district_available": False, "district_note": "Drill-down blocked: loaded sources are state-level only."}

        items = [{"name": r["key"], "ventures": r["ventures"], "ratio": r["value"]} for r in ratios if r["ventures"] > 0]
        clustering = None
        if len(items) >= k + 2:
            clustering = cluster_states(items, k)
        return self.ok({"concentration": concentration, "fy_subsidy_geography": fy, "coverage": coverage, "clustering": clustering},
                       ["Clusters describe numbers; they do not rank states as good or bad.",
                        "Cumulative distributions cannot show a recent surge or decline.",
                        "Per-capita rates need an eligible-population denominator that is not loaded."])
