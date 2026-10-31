"""Shared types: roles, tool context/response envelope and agent result."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Role(str, Enum):
    public = "public"      # aggregate-only, small cells suppressed
    analyst = "analyst"    # verified analyst, approved agency scope
    reviewer = "reviewer"  # validates outlier alerts, documents disposition
    steward = "steward"    # approves source versions, ingestion/admin


class ToolContext(BaseModel):
    """Every tool call carries these four fields (architecture section 06)."""
    trace_id: str
    actor_role: Role
    dataset_version: str
    source_date: str | None = None


class ToolResponse(BaseModel):
    ok: bool
    tool: str
    data: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    agent_id: str
    name: str
    status: Literal["ok", "declined", "unavailable", "abstained"]
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)  # tool-call references backing each statement
    caveats: list[str] = Field(default_factory=list)
