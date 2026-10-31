"""Expose the seven read-only tools over the Model Context Protocol (stdio by default).

    pip install ".[mcp]"
    ACABC_ACTOR_ROLE=analyst python -m acabc.mcp_server

MCP is standardised tool access, not the data warehouse or the model: every call goes through the same
ToolServer used by the API, so RBAC, strict arguments, suppression and audit logging are identical.
The role is fixed per server process (env ACABC_ACTOR_ROLE, default 'public'); a client cannot raise it.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from .models import Role, ToolContext
from .state import AppState, build_state
from .tools import TOOL_DESCRIPTIONS, ToolServer


def build_server(state: AppState | None = None, role: Role | None = None) -> Any:
    state = state or build_state(audit_path=os.environ.get("ACABC_AUDIT_LOG"))
    role = role or Role(os.environ.get("ACABC_ACTOR_ROLE", "public").lower())
    tools = ToolServer(state)
    server = _Server("ind-acabc-architecture-ai", instructions=(
        "Read-only ACABC decision-support tools. No loan, subsidy or fraud decisions; aggregates only. "
        "Cite source, scope and reporting date for every figure."))

    def dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
        ctx = ToolContext(trace_id=uuid.uuid4().hex[:16], actor_role=role, dataset_version=state.active_dataset_version)
        r = tools.call(name, {k: v for k, v in args.items() if v is not None}, ctx)
        return r.model_dump()

    @server.tool(name="acabc.dataset_profile", description=TOOL_DESCRIPTIONS["acabc.dataset_profile"])
    def dataset_profile(dataset_version: str | None = None) -> dict:
        return dispatch("acabc.dataset_profile", {"dataset_version": dataset_version})

    @server.tool(name="acabc.aggregate_query", description=TOOL_DESCRIPTIONS["acabc.aggregate_query"])
    def aggregate_query(metric: str, states: list[str] | None = None, group_by: str = "state", top: int | None = None) -> dict:
        return dispatch("acabc.aggregate_query", {"metric": metric, "states": states, "group_by": group_by, "top": top})

    @server.tool(name="acabc.validate_financials", description=TOOL_DESCRIPTIONS["acabc.validate_financials"])
    def validate_financials(unit: str, group: str = "nabard_fy2026-27", metric: str = "subsidy_released") -> dict:
        return dispatch("acabc.validate_financials", {"unit": unit, "group": group, "metric": metric})

    @server.tool(name="gov.get_benchmark", description=TOOL_DESCRIPTIONS["gov.get_benchmark"])
    def get_benchmark(benchmark_id: str | None = None, agency: str | None = None, scope: str | None = None, indicator: str | None = None) -> dict:
        return dispatch("gov.get_benchmark", {"benchmark_id": benchmark_id, "agency": agency, "scope": scope, "indicator": indicator})

    @server.tool(name="gov.reconcile_reports", description=TOOL_DESCRIPTIONS["gov.reconcile_reports"])
    def reconcile_reports(source_a: str, source_b: str, metric: str) -> dict:
        return dispatch("gov.reconcile_reports", {"source_a": source_a, "source_b": source_b, "metric": metric})

    @server.tool(name="policy.search_official", description=TOOL_DESCRIPTIONS["policy.search_official"])
    def search_official(query: str, cutoff_date: str | None = None) -> dict:
        return dispatch("policy.search_official", {"query": query, "cutoff_date": cutoff_date})

    @server.tool(name="report.export_audit", description=TOOL_DESCRIPTIONS["report.export_audit"])
    def export_audit(trace_id: str, format: str = "csv") -> dict:
        return dispatch("report.export_audit", {"trace_id": trace_id, "format": format})

    return server


def main() -> None:  # pragma: no cover
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
