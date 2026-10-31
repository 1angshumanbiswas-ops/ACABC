"""Agent 06: Audit, Reports & Explanations. Evidence-linked reports and the discrepancy log."""
from __future__ import annotations

from ..models import AgentResult
from .base import Agent

SOURCES = ["mis_2026-10-26", "manage_statewise_2026-10-01", "nabard_xii_f_fy2026-27", "nabard_xii_f_cumulative"]


def inr(n: float, d: int = 0) -> str:
    """Indian digit grouping: 1,23,456 (lakh/crore style)."""
    s = f"{abs(n):.{d}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + whole + (f".{frac}" if frac else "")


class AuditReports(Agent):
    agent_id, name = "06", "Audit, Reports & Explanations"

    def run(self, results: dict[str, AgentResult] | None = None, filters: dict | None = None,
            reconcile_only: bool = False, **_: object) -> AgentResult:
        results = results or {}
        filters = filters or {}
        bm = self.call("gov.get_benchmark", {})
        if not bm.ok:
            return self.result("unavailable", {}, ["Benchmarks could not be read."])
        by_id = {b["id"]: b for b in bm.data["benchmarks"]}
        mis, mg, nb, nbc = (by_id[i] for i in SOURCES)

        log = []
        for metric in ("trained", "ventures"):
            rec = self.call("gov.reconcile_reports", {"source_a": "mis_2026-10-26", "source_b": "manage_statewise_2026-10-01", "metric": metric})
            if rec.ok:
                d = rec.data
                log.append({"metric": metric, "mis": d["a"]["value"], "manage": d["b"]["value"], "difference_mis_minus_manage": d.get("difference"),
                            "higher": d.get("higher"), "status": d["status"], "warnings": d["warnings"]})

        if reconcile_only:
            return self.ok({"discrepancy_log": log, "benchmarks": [mis, mg, nb, nbc]},
                           ["Sources have different refresh schedules and definitions; the gap is documented, never averaged."])

        sections, tables = [], []
        sections.append({"heading": "1. National figures (cumulative, different sources, never averaged)", "lines": [
            f"ACABC MIS, observed {mis['reference_date']}: {inr(mis['values']['trained'])} trained; {inr(mis['values']['ventures'])} agri-ventures.",
            f"MANAGE state-wise, {mg['scope']}: {inr(mg['values']['trained'])} trained; {inr(mg['values']['ventures'])} agri-ventures.",
            "Differences: " + "; ".join(
                f"{l['metric']}: {l['higher'].split('_')[0].upper()} higher by {inr(abs(l['difference_mis_minus_manage']))}" for l in log if l["difference_mis_minus_manage"]) + ". Unresolved; reconciliation required, not averaging.",
            f"NABARD FY 2026-27 to {nb['reference_date']}: {nb['values']['schemes']} schemes; Rs {nb['values']['subsidy_released']:.2f} lakh released "
            f"(cumulative {inr(nbc['values']['schemes'])} schemes; Rs {inr(nbc['values']['subsidy_released'], 2)} lakh). Unit is lakh, not crore; schemes, not beneficiaries."]})
        tables.append({"name": "Benchmark register", "columns": ["source", "scope", "as_of", "trained", "ventures_or_schemes", "subsidy_lakh"], "rows": [
            [mis["agency"], mis["scope"], mis["reference_date"], mis["values"]["trained"], mis["values"]["ventures"], "n/a"],
            [mg["agency"], mg["scope"], mg["reference_date"], mg["values"]["trained"], mg["values"]["ventures"], "n/a"],
            [nb["agency"], nb["scope"], nb["reference_date"], "n/a", nb["values"]["schemes"], nb["values"]["subsidy_released"]],
            [nbc["agency"], nbc["scope"], nbc["reference_date"], "n/a", nbc["values"]["schemes"], nbc["values"]["subsidy_released"]]]})
        tables.append({"name": "Discrepancy log (MIS vs MANAGE)", "columns": ["metric", "MIS", "MANAGE", "MIS_minus_MANAGE", "status"],
                       "rows": [[l["metric"], l["mis"], l["manage"], l["difference_mis_minus_manage"], l["status"]] for l in log]})

        geo = results.get("03")
        if geo and geo.status == "ok":
            c = geo.data["concentration"]
            sections.append({"heading": "2. Geography (MANAGE cumulative ventures)", "lines": [
                f"Top three states hold {c['top3_share_of_national'] * 100:.1f}% of ventures: " + ", ".join(f"{t['state']} ({inr(t['ventures'])})" for t in c["top3"]) + ".",
                c["note"]]})
            tables.append({"name": "Top states by ventures", "columns": ["state", "ventures"], "rows": [[t["state"], t["ventures"]] for t in c["top3"]]})
            cl = geo.data.get("clustering")
            if cl:
                sections[-1]["lines"].append(f"Clustering (k={cl['k']}): stability {cl['stability']:.2f}, silhouette {cl['silhouette']:.2f}, "
                                             f"agreement with plain size rule {cl['baseline_agreement']:.2f}. {cl['verdict_note']}")
        fin = results.get("02")
        if fin and fin.status == "ok":
            d = fin.data
            sections.append({"heading": "3. Finance (NABARD FY 2026-27 to date, Rs lakh)", "lines": [
                f"Robust screen ({d['model_version']}): median {d['median']:.2f} lakh/scheme, MAD {d['mad']:.2f}; "
                f"{len(d['review'])} state(s) beyond {d['thresholds']['review']}, {len(d['watch'])} on watch. Flags are for human review only."]})
            tables.append({"name": "Subsidy per scheme screen", "columns": ["state", "schemes", "subsidy_lakh", "avg_lakh_per_scheme", "robust_z", "status"],
                           "rows": [[r["state"], r["schemes"], r["subsidy_lakh"], r["avg_lakh_per_scheme"], r["robust_z"], r["status"]] for r in d["rows"]]})
        sections.append({"heading": "4. Limitations", "lines": [
            "Ratios compare cumulative totals and are not conversion, approval or survival rates.",
            "Ratios are suppressed where fewer than 100 candidates were trained.",
            "The record-level ACABC file, schema, period and licence have not been confirmed. No model accuracy is claimed.",
            "Averages for states with 1-2 schemes reflect single projects.",
            "No district view: loaded sources are state-level."]})

        report = {
            "title": "IND_ACABC_Architecture_ai: evidence memo",
            "subtitle": "Independent analysis; no Government or MeitY endorsement implied.",
            "sections": sections, "tables": tables, "discrepancy_log": log,
            "appendix": {"dataset_version": self.ctx.dataset_version, "filters": filters,
                         "sources": [{"id": b["id"], "agency": b["agency"], "scope": b["scope"], "reference_date": b["reference_date"],
                                      "source_url": b["source_url"]} for b in (mis, mg, nb, nbc)],
                         "agents_used": sorted(results) + ["06"], "actor_role": self.ctx.actor_role.value},
        }
        stored = self.tools.state.reports.put(self.ctx.trace_id, report)
        self.tools.state.audit.append(trace_id=self.ctx.trace_id, event="report_generated", artifact_hash=stored["artifact_hash"])
        return self.ok({"report": report, "artifact_hash": stored["artifact_hash"], "trace_id": self.ctx.trace_id,
                        "export": "POST /v1/reports/export {trace_id, format}"})
