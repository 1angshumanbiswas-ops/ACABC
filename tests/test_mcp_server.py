import asyncio

import pytest

pytest.importorskip("mcp")

from acabc.mcp_server import build_server  # noqa: E402
from acabc.models import Role  # noqa: E402
from acabc.state import build_state  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_server_lists_exactly_the_seven_tools():
    s = build_server(build_state(), Role.analyst)
    names = {t.name for t in run(s.list_tools())}
    assert names == {"acabc.dataset_profile", "acabc.aggregate_query", "acabc.validate_financials", "gov.get_benchmark",
                     "gov.reconcile_reports", "policy.search_official", "report.export_audit"}


def _payload(res):
    """Normalise across mcp 1.x (tuple/dict) and 2.x (CallToolResult with JSON text content)."""
    import json
    if isinstance(res, tuple):  # mcp 1.x: (content, structured)
        res = res[1] if res[1] else res[0]
    if isinstance(res, dict):
        return res.get("result", res)
    sc = getattr(res, "structured_content", None)
    if sc:
        return sc.get("result", sc)
    content = getattr(res, "content", None) or res
    return json.loads(content[0].text)


def test_calls_go_through_the_same_guardrails_and_role_is_fixed_by_the_process():
    st = build_state()
    pub = build_server(st, Role.public)
    out = _payload(run(pub.call_tool("acabc.dataset_profile", {})))
    assert out["ok"] is False and out["error"]["code"] == "forbidden"
    ana = build_server(st, Role.analyst)
    out = _payload(run(ana.call_tool("gov.reconcile_reports", {"source_a": "mis_2026-10-26", "source_b": "manage_statewise_2026-10-01", "metric": "trained"})))
    assert out["ok"] and out["data"]["difference"] == -1041
    assert any(e.get("tool") == "gov.reconcile_reports" for e in st.audit.entries())
