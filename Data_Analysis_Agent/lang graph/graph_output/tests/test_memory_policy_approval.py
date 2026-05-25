from __future__ import annotations

from data_agent_backend.models.approvals import ApprovalDecision
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.memory import MemoryStatus


def test_memory_lifecycle_and_risk_flags(services):
    namespace = ["user", "u1", "project", "p1"]
    record = services.memory_store.propose_memory(
        namespace,
        "business_glossary",
        "email,name\nalice@example.com,Alice\nbob@example.com,Bob\n1,2\n3,4\n5,6",
        {"artifact_id": "a1"},
        context=PolicyContext(user_id="u1", project_id="p1"),
    )
    assert record.status == MemoryStatus.pending
    assert {"email_pattern", "csv_like_rows"} <= set(record.risk_flags)
    assert services.memory_store.list_memory(namespace) == []
    active = services.memory_store.approve_memory(record.memory_id, "reviewer")
    assert active.status == MemoryStatus.active
    assert len(services.memory_store.list_memory(namespace)) == 1
    archived = services.memory_store.archive_memory(record.memory_id, "reviewer")
    assert archived.status == MemoryStatus.archived
    assert services.memory_store.list_memory(namespace) == []


def test_policy_audit_and_approval_resolution(services):
    decision = services.policy_engine.evaluate("export.create", "/exports/foo.csv", {}, PolicyContext(run_id="run1"))
    assert decision.requires_approval is True
    blocked = services.policy_engine.evaluate("sql.run", "duckdb", {"blocked": True, "reason": "DDL"}, PolicyContext(run_id="run1"))
    assert blocked.allowed is False
    logs = services.sqlite.query_all("SELECT * FROM policy_audit_logs")
    assert len(logs) == 2

    approval = services.approval_store.create_approval_request("export.create", "/exports", {"token": "secret", "format": "csv"})
    assert approval.payload["token"] == "[REDACTED]"
    resolved = services.approval_store.resolve_approval_request(
        approval.approval_id,
        ApprovalDecision.edit,
        edited_payload={"format": "csv", "destination": "local"},
        decided_by="reviewer",
    )
    assert resolved.status.value == "edited"
    assert resolved.edited_payload == {"format": "csv", "destination": "local"}

