"""Agent 05: Policy & Scheme Knowledge. Citation-grounded answers from the versioned corpus, with abstention."""
from __future__ import annotations

from datetime import date

from ..models import AgentResult
from .base import Agent


class PolicyKnowledge(Agent):
    agent_id, name = "05", "Policy & Scheme Knowledge"

    def run(self, question: str = "", cutoff: date | None = None, **_: object) -> AgentResult:
        args: dict = {"query": question}
        if cutoff:
            args["cutoff_date"] = cutoff.isoformat()
        r = self.call("policy.search_official", args)
        if not r.ok:
            return self.result("unavailable", {"error": r.error})
        d = r.data
        if d["abstained"]:
            return self.result("abstained", {"reason": d["reason"], "message": d["message"], "flags": d["flags"]},
                               ["No unsupported eligibility, rate or sanction claim is made."])
        cites = [{"doc_id": p["doc_id"], "title": p["title"], "source_url": p["source_url"], "effective_date": p["effective_date"],
                  "superseded": p["superseded"], "verification_status": p["verification_status"]} for p in d["passages"]]
        return self.ok({"passages": d["passages"], "citations": cites, "flags": d["flags"]},
                       ["Passages are paraphrased from project documents and still need checking against the official text.",
                        "This is explanation only: no eligibility determination, subsidy sanction, bank decision or application is implied."])
