"""FastAPI surface (architecture section 10). Roles come from the X-Actor-Role header in this reference build.

SECURITY: the header is a stand-in for real authentication. Before any non-demo deployment, replace
`get_role` with a verified identity provider (OIDC/SSO) that issues the role claim. See docs/SECURITY.md.
"""
import base64
import os
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .agents.financial import MODEL_VERSION, REVIEW_Z, WATCH_Z
from .models import Role, ToolResponse
from .orchestrator import Orchestrator
from .sources import verify_seed
from .state import AppState, build_state

_STATUS = {"forbidden": 403, "not_found": 404, "tool_not_found": 404, "data_not_loaded": 409, "dimension_unavailable": 422,
           "invalid_arguments": 422, "invalid_filter": 422, "format_unavailable": 501}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricsQuery(_Body):
    metric: Literal["trained", "ventures", "ventures_per_trained", "schemes", "subsidy_released", "avg_subsidy_per_scheme",
                    "records", "assistance_total", "assistance_mean"]
    states: list[str] | None = Field(None, max_length=40)
    group_by: Literal["national", "state", "enterprise_type", "district"] = "state"
    top: int | None = Field(None, ge=1, le=40)


class ReconcileBody(_Body):
    source_a: str
    source_b: str
    metric: str


class ScreenBody(_Body):
    review_z: float = Field(REVIEW_Z, ge=2.0, le=10.0)
    watch_z: float = Field(WATCH_Z, ge=0.5, le=5.0)
    open_cases: bool = True


class PolicyBody(_Body):
    question: str = Field(min_length=3, max_length=300)
    cutoff_date: date | None = None


class ExportBody(_Body):
    trace_id: str | None = Field(None, max_length=64)
    format: Literal["csv", "json", "pdf"] = "csv"


class DispositionBody(_Body):
    decision: Literal["no_action", "needs_clarification", "escalate_to_programme_official"]
    note: str = Field("", max_length=500)


class AskBody(_Body):
    question: str = Field(min_length=3, max_length=500)


def create_app(state: AppState | None = None) -> FastAPI:
    state = state or build_state(audit_path=os.environ.get("ACABC_AUDIT_LOG"))
    orch = Orchestrator(state)
    app = FastAPI(title="IND_ACABC_Architecture_ai", version="0.1.0",
                  description="ACABC geo-financial decision intelligence. Decision support only: no loan, subsidy or fraud decisions.")
    app.state.acabc = state
    app.state.orchestrator = orch

    def get_role(x_actor_role: Annotated[str, Header()] = "public") -> Role:
        try:
            return Role(x_actor_role.lower())
        except ValueError:
            raise HTTPException(400, f"X-Actor-Role must be one of {[r.value for r in Role]}") from None

    RoleDep = Annotated[Role, Depends(get_role)]

    def unwrap(resp: ToolResponse) -> dict[str, Any]:
        if not resp.ok:
            raise HTTPException(_STATUS.get(resp.error["code"], 400), {"code": resp.error["code"], "message": resp.error["message"],
                                                                      "trace_id": resp.meta["trace_id"]})
        return {"trace_id": resp.meta["trace_id"], "dataset_version": resp.meta["dataset_version"], "source_dates": resp.meta["source_dates"], **resp.data}

    def call(tool: str, args: dict, role: Role, trace_id: str | None = None) -> dict:
        return unwrap(orch.tools.call(tool, args, orch.context(role, trace_id)))

    @app.get("/healthz")
    def healthz() -> dict:
        checks = verify_seed()
        return {"status": "ok" if all(c["passed"] for c in checks) and state.audit.verify() else "degraded",
                "dataset_version": state.active_dataset_version, "seed_checks": checks, "audit_chain_valid": state.audit.verify()}

    @app.get("/v1/tools")
    def tools() -> dict:
        return {"tools": orch.tools.list_tools()}

    @app.get("/v1/coverage")
    def coverage(role: RoleDep) -> dict:
        s = state.seed
        private = state.private
        out: dict[str, Any] = {
            "dataset_version": state.active_dataset_version, "role": role.value,
            "sources": [{"id": b["id"], "agency": b["agency"], "scope": b["scope"], "reference_date": b["reference_date"],
                         "indicators": list(b["values"]), "units": b["units"]} for b in s.benchmarks.values()],
            "geography": {"levels": ["national", "state"] + (["district"] if private and private.has("district") else []),
                          "states_in_manage_table": len(s.manage), "district_available": bool(private and private.has("district"))},
            "periods": {"manage": "cumulative to 2026-10-01", "nabard": "FY 2026-27 to 2026-09-30 and cumulative"},
            "metrics": ["trained", "ventures", "ventures_per_trained", "schemes", "subsidy_released", "avg_subsidy_per_scheme"],
            "rights": {"record_level_loaded": private is not None, "status": "licence and year range unconfirmed (AIKosh metadata); M0 pending"
                       if private is None else "confirmed in schema map"},
            "suppression": {"public_min_cell": state.public_min_cell, "ratio_min_trained": state.ratio_min_trained},
        }
        if role is not Role.public and private:
            out["record_level_fields"] = list(private.columns_available)
        return out

    @app.post("/v1/metrics/query")
    def metrics_query(body: MetricsQuery, role: RoleDep) -> dict:
        return call("acabc.aggregate_query", body.model_dump(exclude_none=True), role)

    @app.get("/v1/benchmarks/{benchmark_id}")
    def benchmark(benchmark_id: str, role: RoleDep) -> dict:
        return call("gov.get_benchmark", {"benchmark_id": benchmark_id}, role)

    @app.post("/v1/reconcile")
    def reconcile(body: ReconcileBody, role: RoleDep) -> dict:
        return call("gov.reconcile_reports", body.model_dump(), role)

    @app.post("/v1/anomalies/screen")
    def screen(body: ScreenBody, role: RoleDep) -> dict:
        if role is Role.public:
            raise HTTPException(403, {"code": "forbidden", "message": "Anomaly screening requires an approved analyst, reviewer or steward role."})
        ctx = orch.context(role)
        res = orch.run_agent("02", ctx, review_z=body.review_z, watch_z=body.watch_z)
        if res.status != "ok":
            raise HTTPException(409, {"code": "screen_unavailable", "message": "; ".join(res.caveats)})
        cases = []
        if body.open_cases:
            for r in res.data["rows"]:
                if r["status"] == "review":
                    cases.append(state.reviews.open_case(trace_id=ctx.trace_id, model_ver=MODEL_VERSION, group=r["state"],
                                                         score=r["robust_z"], reasons=r["reasons"]))
        return {"trace_id": ctx.trace_id, "model_version": MODEL_VERSION, "result": res.model_dump(), "cases_opened": cases,
                "notice": "Statistical flags for human review. Not fraud findings."}

    @app.get("/v1/anomalies/cases")
    def cases(role: RoleDep) -> dict:
        if role not in (Role.reviewer, Role.steward):
            raise HTTPException(403, {"code": "forbidden", "message": "Case access requires reviewer authorisation."})
        return {"cases": state.reviews.all()}

    @app.post("/v1/anomalies/{case_id}/disposition")
    def disposition(case_id: str, body: DispositionBody, role: RoleDep, x_actor_id: Annotated[str, Header()] = "unknown") -> dict:
        if role not in (Role.reviewer, Role.steward):
            raise HTTPException(403, {"code": "forbidden", "message": "Only reviewers record dispositions."})
        try:
            return state.reviews.disposition(case_id, x_actor_id, body.decision, body.note)
        except KeyError:
            raise HTTPException(404, {"code": "not_found", "message": "Unknown case."}) from None
        except PermissionError as exc:
            raise HTTPException(409, {"code": "already_dispositioned", "message": str(exc)}) from None

    @app.post("/v1/policy/answer")
    def policy_answer(body: PolicyBody, role: RoleDep) -> dict:
        ctx = orch.context(role)
        res = orch.run_agent("05", ctx, question=body.question, cutoff=body.cutoff_date)
        return {"trace_id": ctx.trace_id, "result": res.model_dump()}

    @app.post("/v1/reports/export")
    def export(body: ExportBody, role: RoleDep, download: Annotated[bool, Query()] = False):
        if role is Role.public:
            raise HTTPException(403, {"code": "forbidden", "message": "Report export requires an approved analyst, reviewer or steward role."})
        trace = body.trace_id
        if trace is None:  # convenience: build a fresh evidence memo for this caller first
            built = orch.handle("evidence report", role)
            trace = built["trace_id"]
        out = call("report.export_audit", {"trace_id": trace, "format": body.format}, role, trace)
        if download:
            raw = base64.b64decode(out["content"]) if out["encoding"] == "base64" else out["content"].encode()
            mt = {"csv": "text/csv", "json": "application/json", "pdf": "application/pdf"}[body.format]
            return Response(raw, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'})
        return out

    @app.post("/v1/ask")
    def ask(body: AskBody, role: RoleDep) -> dict:
        return orch.handle(body.question, role)

    @app.get("/v1/audit/verify")
    def audit_verify(role: RoleDep) -> dict:
        if role is not Role.steward:
            raise HTTPException(403, {"code": "forbidden", "message": "Steward only."})
        return {"valid": state.audit.verify(), "entries": len(state.audit.entries())}

    @app.get("/v1/dataset/profile")
    def dataset_profile(role: RoleDep) -> dict:
        return call("acabc.dataset_profile", {}, role)

    return app


app = create_app()
