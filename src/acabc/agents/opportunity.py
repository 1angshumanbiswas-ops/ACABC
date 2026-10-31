"""Agent 04: Enterprise Opportunity. Phase 2 only. Declines until authorised external data and expert labels exist."""
from __future__ import annotations

from ..models import AgentResult
from .base import Agent


class EnterpriseOpportunity(Agent):
    agent_id, name = "04", "Enterprise Opportunity (Phase 2)"

    def run(self, **_: object) -> AgentResult:
        return self.result("unavailable", {
            "phase": 2, "enabled": False,
            "prerequisites": ["record-level ACABC enterprise history with confirmed rights (M0)",
                              "authorised local crop-production and market data (DA&FW statistics, e-NAM only with an authorised integration)",
                              "expert-labelled evidence for explainable ranking and uncertainty"],
            "never_claimed": ["business survival", "profit", "loan default or approval", "guaranteed farm business income"],
        }, ["Opportunity ranking is not available in V1. No outcome labels exist, so no survival or profit prediction is made."])
