"""Agent base class. Agents never touch data directly: every fact comes through an MCP tool call."""
from __future__ import annotations

import json
from typing import Any

from ..models import AgentResult, ToolContext, ToolResponse
from ..tools import ToolServer


class Agent:
    agent_id = "00"
    name = "agent"

    def __init__(self, tools: ToolServer, ctx: ToolContext) -> None:
        self.tools, self.ctx = tools, ctx
        self._evidence: list[str] = []
        self._caveats: list[str] = []

    def call(self, tool: str, args: dict | None = None) -> ToolResponse:
        resp = self.tools.call(tool, args, self.ctx)
        ref = f"{tool}({json.dumps(args or {}, sort_keys=True, default=str)})"
        if resp.ok:
            dates = ",".join(resp.meta.get("source_dates", [])) or "n/a"
            self._evidence.append(f"{ref} @ {dates}")
        else:
            self._caveats.append(f"{tool} unavailable: {resp.error['code']} ({resp.error['message']})")
        return resp

    def ok(self, data: dict[str, Any], caveats: list[str] | None = None) -> AgentResult:
        return AgentResult(agent_id=self.agent_id, name=self.name, status="ok", data=data,
                           evidence=list(dict.fromkeys(self._evidence)), caveats=list(dict.fromkeys(self._caveats + (caveats or []))))

    def result(self, status: str, data: dict[str, Any], caveats: list[str] | None = None) -> AgentResult:
        return AgentResult(agent_id=self.agent_id, name=self.name, status=status, data=data,  # type: ignore[arg-type]
                           evidence=list(dict.fromkeys(self._evidence)), caveats=list(dict.fromkeys(self._caveats + (caveats or []))))

    def run(self, **params: Any) -> AgentResult:  # pragma: no cover - abstract
        raise NotImplementedError
