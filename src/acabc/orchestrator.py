"""The single rule-based orchestrator: classify intent, apply guardrails, run agents, compose an answer.

Deliberately not an LLM: routing is transparent, testable and cannot be talked out of its guardrails.
An optional language model may later phrase answers from agent output, never choose tools or data.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date

from .agents import AGENTS
from .agents.audit_reports import inr
from .guardrails import check_request, looks_like_injection
from .models import AgentResult, Role, ToolContext
from .state import AppState
from .tools import ToolServer

_INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("report", re.compile(r"\b(report|memo|evidence pack|brief)\b", re.I)),
    ("reconcile", re.compile(r"reconcil|discrepan|disagree|\bdiffer\w*|\bmis\b.*\bmanage\b|\bmanage\b.*\bmis\b|which (figure|number) is right", re.I)),
    ("policy", re.compile(r"\b(policy|circular|guideline\w*|compendium|jansamarth|guarantee\w*|eligib\w*|rates?|how much subsidy|loan|apply|scheme rules?)\b", re.I)),
    ("opportunity", re.compile(r"opportunit|which enterprise|what business|recommend\w* .*(business|enterprise)|best (business|enterprise)", re.I)),
    ("finance", re.compile(r"outlier|anomal|unusual|per scheme|average subsidy|screen|flag|subsid\w*|nabard|financ\w*|schemes?\b", re.I)),
    ("geography", re.compile(r"cluster|geograph|concentrat|\bstates?\b|top \w+|region\w*|where|which state", re.I)),
]
_PLANS = {
    "overview": ["01", "03"], "geography": ["03"], "finance": ["02"], "reconcile": ["06"],
    "policy": ["05"], "opportunity": ["04"], "report": ["01", "02", "03", "06"],
}


def classify(question: str) -> str:
    for name, pat in _INTENTS:
        if pat.search(question):
            return name
    return "overview"


class Orchestrator:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.tools = ToolServer(state)

    def context(self, role: Role, trace_id: str | None = None) -> ToolContext:
        return ToolContext(trace_id=trace_id or uuid.uuid4().hex[:16], actor_role=role, dataset_version=self.state.active_dataset_version)

    def run_agent(self, agent_id: str, ctx: ToolContext, **params) -> AgentResult:
        return AGENTS[agent_id](self.tools, ctx).run(**params)

    def handle(self, question: str, role: Role = Role.public, trace_id: str | None = None, cutoff: date | None = None) -> dict:
        ctx = self.context(role, trace_id)
        qhash = hashlib.sha256(question.encode()).hexdigest()[:16]
        decision = check_request(question)
        flags = ["instruction_like_text_ignored"] if looks_like_injection(question) else []
        if not decision.allowed:
            self.state.audit.append(trace_id=ctx.trace_id, event="request_declined", code=decision.code, question_sha256=qhash, actor_role=role.value)
            return {"trace_id": ctx.trace_id, "intent": decision.code, "role": role.value, "declined": True, "decision": decision.code,
                    "plan": [], "results": {}, "answer": decision.message, "caveats": [], "flags": flags}

        intent = classify(question)
        plan = _PLANS[intent]
        self.state.audit.append(trace_id=ctx.trace_id, event="request_routed", intent=intent, plan=plan, question_sha256=qhash, actor_role=role.value)
        results: dict[str, AgentResult] = {}
        for aid in plan:
            if aid == "05":
                results[aid] = self.run_agent(aid, ctx, question=question, cutoff=cutoff)
            elif aid == "06":
                results[aid] = self.run_agent(aid, ctx, results=results, reconcile_only=(intent == "reconcile"), filters={"question_intent": intent})
            else:
                results[aid] = self.run_agent(aid, ctx)
        caveats = list(dict.fromkeys(c for r in results.values() for c in r.caveats))
        return {"trace_id": ctx.trace_id, "intent": intent, "role": role.value, "declined": False, "decision": "ok",
                "plan": [{"agent": a, "name": results[a].name, "status": results[a].status} for a in plan],
                "results": {a: r.model_dump() for a, r in results.items()}, "answer": compose(intent, results), "caveats": caveats, "flags": flags}


def compose(intent: str, res: dict[str, AgentResult]) -> str:
    if intent == "reconcile":
        log = res["06"].data["discrepancy_log"]
        parts = [f"{l['metric']}: MIS {inr(l['mis'])} vs MANAGE {inr(l['manage'])} ({l['higher'].split('_')[0].upper()} higher by {inr(abs(l['difference_mis_minus_manage']))})" for l in log]
        return "; ".join(parts) + ". The two official sources disagree; the gap is unresolved and is not averaged."
    if intent == "policy":
        r = res["05"]
        if r.status == "abstained":
            return r.data["message"]
        p = r.data["passages"][0]
        return f"{p['text']} [{p['authority']}: {p['title']}; {p['source_url']}; effective {p['effective_date'] or 'date to confirm'}]"
    if intent == "opportunity":
        return "Not available in V1 (Phase 2). " + res["04"].caveats[0]
    if intent == "finance":
        d = res["02"].data
        if res["02"].status != "ok":
            return "Financial screening is unavailable: " + "; ".join(res["02"].caveats)
        return (f"Median subsidy per scheme is Rs {d['median']:.2f} lakh (MAD {d['mad']:.2f}) across {d['n_groups']} states, FY 2026-27 to date. "
                f"{len(d['review'])} state(s) beyond robust z {d['thresholds']['review']}: {', '.join(d['review']) or 'none'}; "
                f"{len(d['watch'])} on watch. Flags are for human review, never a fraud signal.")
    if intent in ("geography", "overview"):
        g = res["03"].data
        c, fy = g["concentration"], g["fy_subsidy_geography"]
        txt = (f"{', '.join(t['state'] for t in c['top3'])} hold {c['top3_share_of_national'] * 100:.1f}% of cumulative ventures (MANAGE, 1 Oct 2026). "
               f"In FY 2026-27 to date, {fy['states_with_schemes']} of {fy['states_listed']} states report NABARD schemes")
        if "lead_state" in fy:
            ls = fy["lead_state"]
            txt += f"; {ls['state']} has {ls['share_of_schemes'] * 100:.1f}% of schemes and {ls['share_of_subsidy'] * 100:.1f}% of subsidy"
        return txt + ". Concentration is a measurement, not evidence of unmet demand or failure."
    if intent == "report":
        r = res["06"]
        return f"Evidence memo generated (trace {r.data['trace_id']}, hash {r.data['artifact_hash'][:12]}). Export via POST /v1/reports/export."
    return ""
