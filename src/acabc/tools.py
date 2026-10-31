"""The seven read-only MCP tools (architecture section 06) behind one guarded entry point.

Guarantees enforced here, not left to callers:
  * deny by default: unknown tools, extra/unbounded arguments and any SQL-like input are rejected;
  * no write or execute operations exist; no tool returns identifiable beneficiary rows;
  * every call needs trace_id, actor_role, dataset_version and is audit-logged with source dates;
  * small cells are suppressed for the public role; ratios are suppressed below 100 trained.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .models import Role, ToolContext, ToolResponse
from .policy import search as policy_search
from .state import AppState
from .statistics import median
from .units import canonical_unit, convert

Metric = Literal["trained", "ventures", "ventures_per_trained", "schemes", "subsidy_released",
                 "avg_subsidy_per_scheme", "records", "assistance_total", "assistance_mean"]
_SEED_COUNT = {"trained", "ventures", "schemes"}
_PRIVATE = {"records", "assistance_total", "assistance_mean"}

TOOL_ROLES: dict[str, frozenset[Role]] = {
    "acabc.dataset_profile": frozenset({Role.steward}),
    "acabc.aggregate_query": frozenset(Role),
    "acabc.validate_financials": frozenset({Role.analyst, Role.reviewer, Role.steward}),
    "gov.get_benchmark": frozenset(Role),
    "gov.reconcile_reports": frozenset(Role),
    "policy.search_official": frozenset(Role),
    "report.export_audit": frozenset({Role.analyst, Role.reviewer, Role.steward}),
}


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DatasetProfileArgs(_Strict):
    dataset_version: str | None = Field(None, max_length=80)


class AggregateQueryArgs(_Strict):
    metric: Metric
    states: list[str] | None = Field(None, max_length=40)
    group_by: Literal["national", "state", "enterprise_type", "district"] = "state"
    top: int | None = Field(None, ge=1, le=40)


class ValidateFinancialsArgs(_Strict):
    group: Literal["nabard_fy2026-27", "private"] = "nabard_fy2026-27"
    metric: Literal["subsidy_released", "assistance_amount"] = "subsidy_released"
    unit: Literal["rupee", "lakh", "crore"]


class GetBenchmarkArgs(_Strict):
    benchmark_id: str | None = Field(None, max_length=80)
    agency: str | None = Field(None, max_length=60)
    scope: str | None = Field(None, max_length=60)
    indicator: str | None = Field(None, max_length=40)


class ReconcileArgs(_Strict):
    source_a: str = Field(max_length=80)
    source_b: str = Field(max_length=80)
    metric: str = Field(max_length=40)


class PolicySearchArgs(_Strict):
    query: str = Field(min_length=3, max_length=300)
    cutoff_date: date | None = None


class ExportArgs(_Strict):
    trace_id: str = Field(min_length=4, max_length=64)
    format: Literal["csv", "json", "pdf"]

    @field_validator("trace_id")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("trace_id must be alphanumeric")
        return v


ARG_MODELS: dict[str, type[_Strict]] = {
    "acabc.dataset_profile": DatasetProfileArgs, "acabc.aggregate_query": AggregateQueryArgs,
    "acabc.validate_financials": ValidateFinancialsArgs, "gov.get_benchmark": GetBenchmarkArgs,
    "gov.reconcile_reports": ReconcileArgs, "policy.search_official": PolicySearchArgs,
    "report.export_audit": ExportArgs,
}
TOOL_DESCRIPTIONS = {
    "acabc.dataset_profile": "Columns, types, period and rights of loaded datasets (steward only).",
    "acabc.aggregate_query": "Bounded counts/totals by geography with source, version and small-cell suppression.",
    "acabc.validate_financials": "Unit check, duplicate and range diagnostics for a financial metric group.",
    "gov.get_benchmark": "Authoritative published aggregate with agency, scope and reporting date.",
    "gov.reconcile_reports": "Difference between two source references on a shared metric, with inability-to-compare warnings.",
    "policy.search_official": "Versioned official-document passages with dated URLs; abstains when unsupported.",
    "report.export_audit": "Evidence-linked CSV/JSON/PDF export with provenance and artifact hash (masked data only).",
}


class ToolServer:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self._impl: dict[str, Callable[[Any, ToolContext], tuple[dict, list[str]]]] = {
            "acabc.dataset_profile": self._dataset_profile, "acabc.aggregate_query": self._aggregate_query,
            "acabc.validate_financials": self._validate_financials, "gov.get_benchmark": self._get_benchmark,
            "gov.reconcile_reports": self._reconcile, "policy.search_official": self._policy,
            "report.export_audit": self._export,
        }

    # ------------------------------------------------------------------ entry point
    def list_tools(self) -> list[dict]:
        return [{"name": n, "description": TOOL_DESCRIPTIONS[n], "read_only": True,
                 "roles": sorted(r.value for r in TOOL_ROLES[n]), "input_schema": ARG_MODELS[n].model_json_schema()}
                for n in self._impl]

    def call(self, name: str, args: dict | None, ctx: ToolContext) -> ToolResponse:
        args = args or {}
        meta = {"trace_id": ctx.trace_id, "actor_role": ctx.actor_role.value, "dataset_version": ctx.dataset_version,
                "tool": name}
        try:
            if name not in self._impl:
                raise ToolError("tool_not_found", f"Unknown tool {name!r}. Only the registered read-only tools exist.")
            if ctx.actor_role not in TOOL_ROLES[name]:
                raise ToolError("forbidden", f"Role {ctx.actor_role.value!r} may not call {name}.")
            try:
                parsed = ARG_MODELS[name].model_validate(args)
            except ValidationError as exc:
                bad = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors()[:4])
                raise ToolError("invalid_arguments", f"Arguments rejected ({bad}).") from None
            data, dates = self._impl[name](parsed, ctx)
            meta["source_dates"] = sorted(set(dates))
            resp = ToolResponse(ok=True, tool=name, data=data, meta=meta)
        except ToolError as err:
            meta["source_dates"] = []
            resp = ToolResponse(ok=False, tool=name, error={"code": err.code, "message": err.message}, meta=meta)
        self.state.audit.append(trace_id=ctx.trace_id, event="tool_call", tool=name, actor_role=ctx.actor_role.value,
                                dataset_version=ctx.dataset_version, args=args, ok=resp.ok,
                                error_code=(resp.error or {}).get("code"), source_dates=meta["source_dates"])
        return resp

    # ------------------------------------------------------------------ tools
    def _dataset_profile(self, a: DatasetProfileArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        s = self.state.seed
        out: dict[str, Any] = {
            "active_dataset_version": self.state.active_dataset_version,
            "seed_aggregates": [
                {"source": "manage_statewise_2026-10-01", "rows": len(s.manage), "columns": {"state": "str", "trained": "int", "ventures": "int"}, "scope": "cumulative", "reference_date": "2026-10-01", "geography": "state/UT"},
                {"source": "nabard_xii_f_fy2026-27", "rows": len(s.nabard), "columns": {"state": "str", "schemes": "int", "subsidy_released_lakh": "float"}, "scope": "fy_2026-27_to_date", "reference_date": "2026-09-30", "geography": "state"},
            ],
            "aikosh_quality_report": s.quality_report,
            "rights": {"licence": s.quality_report["metadata"]["license"], "visibility": s.quality_report["metadata"]["visibility"],
                       "status": "unconfirmed: licence and year range missing in metadata"},
        }
        out["private_record_level"] = (self.state.private.profile() if self.state.private else
                                       {"loaded": False, "reason": "M0 pending: file, dictionary, period and rights not yet confirmed"})
        return out, ["2026-10-01", "2026-09-30", "2025-12-01"]

    def _aggregate_query(self, a: AggregateQueryArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        if a.metric in _PRIVATE:
            return self._aggregate_private(a, ctx)
        if a.group_by in ("enterprise_type", "district"):
            raise ToolError("dimension_unavailable", f"No {a.group_by} dimension in the loaded sources; state-level and national views only.")
        s, st = self.state.seed, self.state
        known = set(s.states)
        bad = sorted(set(a.states or []) - known)
        if bad:
            raise ToolError("invalid_filter", f"Unknown states: {bad}")
        wanted = set(a.states) if a.states else known

        nb = s.nabard_by_state()
        mg = s.benchmarks["manage_statewise_2026-10-01"]
        nbb = s.benchmarks["nabard_xii_f_fy2026-27"]
        if a.metric in {"trained", "ventures", "ventures_per_trained"}:
            src, unit, scope, ref = "manage_statewise_2026-10-01", "persons" if a.metric == "trained" else "ventures", mg["scope"], mg["reference_date"]
        else:
            src, unit, scope, ref = "nabard_xii_f_fy2026-27", {"schemes": "schemes"}.get(a.metric, "rupees_lakh"), nbb["scope"], nbb["reference_date"]
        if a.metric == "ventures_per_trained":
            unit, label = "ratio_of_cumulative_totals", "not a conversion, approval or survival rate"
        else:
            label = None

        rows: list[dict] = []
        for r in s.manage:
            if r.state not in wanted:
                continue
            n = nb.get(r.state)
            row: dict[str, Any] = {"key": r.state, "suppressed": False, "reason": None}
            if a.metric == "trained":
                row["value"] = r.trained
            elif a.metric == "ventures":
                row["value"] = r.ventures
            elif a.metric == "ventures_per_trained":
                row.update(trained=r.trained, ventures=r.ventures)
                if r.trained < st.ratio_min_trained:
                    row.update(value=None, suppressed=True, reason=f"fewer_than_{st.ratio_min_trained}_trained")
                else:
                    row["value"] = round(r.ventures / r.trained, 6)
            elif a.metric == "schemes":
                row["value"] = n.schemes if n else 0
            elif a.metric == "subsidy_released":
                row["value"] = n.subsidy_lakh if n else 0.0
            else:  # avg_subsidy_per_scheme
                row.update(schemes=n.schemes if n else 0)
                if not n:
                    row.update(value=None, suppressed=True, reason="no_schemes_reported")
                elif ctx.actor_role is Role.public and n.schemes < st.public_min_cell:
                    row.pop("schemes", None)  # the count itself is a small cell
                    row.update(value=None, suppressed=True, reason=f"public_small_cell_below_{st.public_min_cell}")
                else:
                    row["value"] = round(n.subsidy_lakh / n.schemes, 4)
            if ctx.actor_role is Role.public and a.metric in _SEED_COUNT and row.get("value") and row["value"] < st.public_min_cell:
                row.update(value=None, suppressed=True, reason=f"public_small_cell_below_{st.public_min_cell}")
            rows.append(row)

        if a.group_by == "national":
            total = self._national(a.metric, mg, nbb)
            return {"metric": a.metric, "unit": unit, "scope": scope, "source": src, "reference_date": ref, "group_by": "national",
                    "rows": [{"key": "India", "value": total, "suppressed": False, "reason": None}], "label": label,
                    "notes": ["Official published total; state rows are not re-summed here."]}, [ref]
        if a.top:
            rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
            rows = rows[: a.top]
        total = self._national(a.metric, mg, nbb)
        if total:
            for r in rows:
                r["share_of_national"] = round(r["value"] / total, 6) if r["value"] is not None and a.metric != "ventures_per_trained" and a.metric != "avg_subsidy_per_scheme" else None
        return {"metric": a.metric, "unit": unit, "scope": scope, "source": src, "reference_date": ref, "group_by": "state",
                "rows": rows, "national_total": total, "label": label,
                "notes": [f"{sum(1 for r in rows if r['suppressed'])} cell(s) suppressed."]}, [ref]

    @staticmethod
    def _national(metric: str, mg: dict, nbb: dict) -> float | None:
        v = {"trained": mg["values"]["trained"], "ventures": mg["values"]["ventures"],
             "ventures_per_trained": round(mg["values"]["ventures"] / mg["values"]["trained"], 6),
             "schemes": nbb["values"]["schemes"], "subsidy_released": nbb["values"]["subsidy_released"],
             "avg_subsidy_per_scheme": round(nbb["values"]["subsidy_released"] / nbb["values"]["schemes"], 4)}
        return v.get(metric)

    def _aggregate_private(self, a: AggregateQueryArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        if ctx.actor_role is Role.public:
            raise ToolError("forbidden", "Record-level derived aggregates require an approved analyst role.")
        p = self.state.private
        if p is None:
            raise ToolError("data_not_loaded", "No record-level ACABC file is loaded (M0 rights gate pending); only published aggregates are available.")
        if a.group_by != "national" and not p.has(a.group_by):
            raise ToolError("dimension_unavailable", f"The loaded file has no mapped {a.group_by} field; the view is blocked, not constructed.")
        df = p.df
        if a.states:
            df = df[df["state"].isin(a.states)]
        keys = [] if a.group_by == "national" else [a.group_by]
        g = df.groupby(a.group_by, dropna=True) if keys else [("India", df)]
        rows = []
        for key, part in g:
            n = len(part)
            row: dict[str, Any] = {"key": key if keys else "India", "n_records": n, "suppressed": False, "reason": None}
            if ctx.actor_role is not Role.steward and n < self.state.public_min_cell:
                row.update(value=None, suppressed=True, reason=f"small_cell_below_{self.state.public_min_cell}")
            elif a.metric == "records":
                row["value"] = n
            elif a.metric == "assistance_total":
                row["value"] = float(part["assistance_amount"].sum())
            else:
                row["value"] = float(part["assistance_amount"].mean())
            rows.append(row)
        if a.top:
            rows.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0)))
            rows = rows[: a.top]
        return {"metric": a.metric, "unit": "rupees" if a.metric != "records" else "records", "scope": "record_level_private",
                "source": p.dataset_version, "reference_date": None, "group_by": a.group_by, "rows": rows,
                "label": None, "notes": ["Derived from restricted record-level data; identifiers hashed; small cells suppressed."]}, []

    def _validate_financials(self, a: ValidateFinancialsArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        issues: list[dict] = []
        if a.group == "private":
            p = self.state.private
            if p is None:
                raise ToolError("data_not_loaded", "No record-level ACABC file is loaded.")
            vals = [float(v) for v in p.df["assistance_amount"].dropna()]
            native = "rupee"
            dup = int(p.report.get("exact_duplicates_dropped", 0))
            printed_gap = None
        else:
            if a.metric != "subsidy_released":
                raise ToolError("invalid_arguments", "NABARD group supports metric 'subsidy_released'.")
            rows = self.state.seed.nabard
            vals = [r.subsidy_lakh for r in rows]
            native = "lakh"
            dup = len(rows) - len({r.state for r in rows})
            printed = self.state.seed.benchmarks["nabard_xii_f_fy2026-27"]["values"]["subsidy_released"]
            printed_gap = round(sum(vals) - printed, 2)
        unit_ok = canonical_unit(a.unit) == native
        if not unit_ok:
            issues.append({"severity": "high", "code": "unit_mismatch",
                           "detail": f"Declared {a.unit} but the source reports {native}. 1,135.03 lakh = {convert(1135.03, 'lakh', 'crore'):.4f} crore, not 1,135.03 crore." if native == "lakh" else f"Declared {a.unit} but file unit is {native}."})
        if dup:
            issues.append({"severity": "high", "code": "duplicates", "detail": f"{dup} duplicate record(s)/state row(s)."})
        neg = sum(1 for v in vals if v < 0)
        if neg:
            issues.append({"severity": "high", "code": "negative_values", "detail": f"{neg} negative value(s)."})
        med = median(vals) if vals else 0
        if med and max(vals) / med > 25:
            issues.append({"severity": "medium", "code": "extreme_range", "detail": f"max/median = {max(vals) / med:.1f}; review comparator groups."})
        if printed_gap is not None and abs(printed_gap) >= 0.05:
            issues.append({"severity": "medium", "code": "printed_total_gap", "detail": f"Rows sum differs from printed total by {printed_gap} lakh."})
        return {"group": a.group, "metric": a.metric, "declared_unit": a.unit, "source_unit": native, "unit_consistent": unit_ok,
                "n_values": len(vals), "min": min(vals) if vals else None, "median": med if vals else None,
                "max": max(vals) if vals else None, "duplicates": dup, "printed_total_gap_lakh": printed_gap,
                "issues": issues, "status": "fail" if any(i["severity"] == "high" for i in issues) else ("warn" if issues else "pass")}, ["2026-09-30"]

    def _get_benchmark(self, a: GetBenchmarkArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        out = []
        for b in self.state.seed.benchmarks.values():
            if a.benchmark_id and b["id"] != a.benchmark_id:
                continue
            if a.agency and a.agency.lower() not in b["agency"].lower():
                continue
            if a.scope and a.scope.lower() not in b["scope"].lower():
                continue
            if a.indicator and a.indicator not in b["values"]:
                continue
            rec = {k: b[k] for k in ("id", "agency", "source_url", "reference_date", "scope", "units")}
            rec["values"] = {a.indicator: b["values"][a.indicator]} if a.indicator else b["values"]
            if "detail" in b and not a.indicator:
                rec["detail"] = b["detail"]
            out.append(rec)
        if not out:
            raise ToolError("not_found", "No published benchmark matches. Nothing is estimated.")
        return {"benchmarks": out}, [b["reference_date"] for b in out]

    def _reconcile(self, a: ReconcileArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        bm = self.state.seed.benchmarks
        for ref in (a.source_a, a.source_b):
            if ref not in bm:
                raise ToolError("not_found", f"Unknown source reference {ref!r}. Known: {sorted(bm)}")
        A, B = bm[a.source_a], bm[a.source_b]
        warnings: list[str] = []
        res: dict[str, Any] = {"metric": a.metric, "a": self._ref(A, a.metric), "b": self._ref(B, a.metric), "status": "unresolved",
                               "comparable": True, "warnings": warnings}
        for tag, src in (("a", A), ("b", B)):
            if a.metric not in src["values"]:
                res["comparable"] = False
                warnings.append(f"Cannot compare: {src['agency']} ({src['id']}) does not report {a.metric!r}. No value is estimated.")
        if res["comparable"]:
            ua, ub = A["units"][a.metric], B["units"][a.metric]
            if ua != ub:
                res["comparable"] = False
                warnings.append(f"Cannot compare: units differ ({ua} vs {ub}).")
            fy_a, fy_b = "fy_" in A["scope"], "fy_" in B["scope"]
            if fy_a != fy_b:
                res["comparable"] = False
                warnings.append("Cannot compare: one source is fiscal-year-to-date and the other cumulative.")
        if res["comparable"]:
            va, vb = A["values"][a.metric], B["values"][a.metric]
            res.update(difference=round(va - vb, 6), abs_difference=round(abs(va - vb), 6),
                       higher=A["id"] if va > vb else (B["id"] if vb > va else None))
            if va != vb:
                warnings.append("Sources differ in observation date, refresh schedule and definitions; the gap is documented, not averaged or resolved.")
        return res, [A["reference_date"], B["reference_date"]]

    @staticmethod
    def _ref(b: dict, metric: str) -> dict:
        return {"id": b["id"], "agency": b["agency"], "scope": b["scope"], "reference_date": b["reference_date"],
                "value": b["values"].get(metric), "unit": b["units"].get(metric)}

    def _policy(self, a: PolicySearchArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        res = policy_search(a.query, a.cutoff_date)
        return res, [p["effective_date"] for p in res["passages"] if p["effective_date"]]

    def _export(self, a: ExportArgs, ctx: ToolContext) -> tuple[dict, list[str]]:
        stored = self.state.reports.get(a.trace_id)
        if stored is None:
            raise ToolError("not_found", f"No report is stored for trace_id {a.trace_id!r}. Run the report workflow first.")
        rep = stored["report"]
        chain = [{"seq": e["seq"], "tool": e.get("tool"), "event": e["event"], "ok": e.get("ok"), "hash": e["hash"][:16]}
                 for e in self.state.audit.entries(a.trace_id)]
        base = {"artifact_hash": stored["artifact_hash"], "trace_id": a.trace_id, "generated_at": stored["generated_at"],
                "dataset_version": rep["appendix"]["dataset_version"], "masked": True,
                "masking_note": "Aggregates only; small cells suppressed; no beneficiary identifiers."}
        if a.format == "json":
            content, enc, name = json.dumps({**base, "report": rep, "audit_chain": chain}, indent=2, default=str), "utf-8", f"acabc_report_{a.trace_id}.json"
        elif a.format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["table", "row", *["col" + str(i + 1) for i in range(6)]])
            for t in rep["tables"]:
                w.writerow([t["name"], "header", *t["columns"]])
                for i, r in enumerate(t["rows"]):
                    w.writerow([t["name"], i + 1, *r])
            w.writerow([])
            w.writerow(["provenance", "key", "value"])
            for k, v in (("trace_id", a.trace_id), ("dataset_version", base["dataset_version"]), ("artifact_hash", base["artifact_hash"]),
                         ("generated_at", base["generated_at"]), ("filters", json.dumps(rep["appendix"]["filters"]))):
                w.writerow(["provenance", k, v])
            for s in rep["appendix"]["sources"]:
                w.writerow(["source", s["id"], f"{s['agency']} | {s['scope']} | as of {s['reference_date']}"])
            content, enc, name = buf.getvalue(), "utf-8", f"acabc_report_{a.trace_id}.csv"
        else:
            try:
                content, enc = base64.b64encode(_render_pdf(rep, base, chain)).decode(), "base64"
            except ImportError as exc:  # pragma: no cover
                raise ToolError("format_unavailable", "PDF export needs the optional 'reportlab' package (pip install .[pdf]).") from exc
            name = f"acabc_report_{a.trace_id}.pdf"
        digest = hashlib.sha256(content.encode()).hexdigest()
        return {"format": a.format, "filename": name, "encoding": enc, "content": content, "content_sha256": digest, **base}, [
            s["reference_date"] for s in rep["appendix"]["sources"]]


def _render_pdf(rep: dict, base: dict, chain: list[dict]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    ss = getSampleStyleSheet()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=rep["title"], leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    el: list[Any] = [Paragraph(escape(rep["title"]), ss["Title"]), Paragraph(escape(rep["subtitle"]), ss["Italic"]), Spacer(1, 8)]
    for sec in rep["sections"]:
        el.append(Paragraph(escape(sec["heading"]), ss["Heading2"]))
        for line in sec["lines"]:
            el.append(Paragraph(escape(line), ss["BodyText"]))
    for t in rep["tables"]:
        el += [Spacer(1, 6), Paragraph(escape(t["name"]), ss["Heading3"])]
        data = [t["columns"], *[[str(c) for c in r] for r in t["rows"]]]
        tb = Table(data, repeatRows=1)
        tb.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
        el.append(tb)
    el.append(Paragraph("Appendix: provenance", ss["Heading2"]))
    for k in ("trace_id", "dataset_version", "artifact_hash", "generated_at", "masking_note"):
        el.append(Paragraph(f"{k}: {escape(str(base[k]))}", ss["BodyText"]))
    for s in rep["appendix"]["sources"]:
        el.append(Paragraph(escape(f"{s['id']} | {s['agency']} | {s['scope']} | as of {s['reference_date']} | {s['source_url']}"), ss["BodyText"]))
    doc.build(el)
    return buf.getvalue()
