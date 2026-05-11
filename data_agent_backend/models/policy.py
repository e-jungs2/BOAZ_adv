from __future__ import annotations

from enum import StrEnum

from .common import BackendModel


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    blocked = "blocked"


class PolicyDecision(BackendModel):
    decision_id: str
    allowed: bool
    requires_approval: bool
    risk_level: RiskLevel
    reason: str
    editable_fields: list[str] = []

