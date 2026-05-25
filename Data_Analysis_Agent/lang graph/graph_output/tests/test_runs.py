from __future__ import annotations

import sqlite3

from data_agent_backend.mcp.tools_runs import run_create_impl, run_update_status_impl
from data_agent_backend.models.artifacts import ArtifactRegisterRequest, ArtifactType
from data_agent_backend.models.contexts import PolicyContext
from data_agent_backend.models.runs import RunStatus
from data_agent_backend.storage.sqlite import SQLiteStore


def test_run_migration_adds_status_and_event_table_to_existing_db(tmp_path):
    db_path = tmp_path / "backend.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO schema_migrations(version) VALUES (1);
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                thread_id TEXT,
                project_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO runs(run_id, metadata_json, created_at, updated_at) VALUES ('run1', '{}', 't1', 't1');
            """
        )

    store = SQLiteStore(db_path)
    run = store.query_one("SELECT status FROM runs WHERE run_id = ?", ("run1",))
    assert run["status"] == "created"
    assert store.query_one("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'run_events'") is not None


def test_run_create_get_and_list_filters(services):
    run = services.run_service.create_run("run1", thread_id="thread1", project_id="project1", metadata={"goal": "profile"})
    services.run_service.create_run("run2", thread_id="thread2", project_id="project1")
    services.run_service.update_status("run2", RunStatus.running)

    assert run.status == RunStatus.created
    assert run.metadata == {"goal": "profile"}
    assert services.run_service.get_run("run1").thread_id == "thread1"
    assert [item.run_id for item in services.run_service.list_runs(thread_id="thread1")] == ["run1"]
    assert [item.run_id for item in services.run_service.list_runs(project_id="project1", status="running")] == ["run2"]


def test_run_status_validation_and_terminal_block(services):
    services.run_service.create_run("run1")

    invalid = run_update_status_impl(run_id="run1", status="bad", services=services)
    assert invalid.ok is False
    assert invalid.error.code == "VALIDATION_ERROR"

    succeeded = services.run_service.update_status("run1", "succeeded")
    assert succeeded.status == RunStatus.succeeded

    blocked = run_update_status_impl(run_id="run1", status="failed", services=services)
    assert blocked.ok is False
    assert blocked.error.code == "RUN_TERMINAL"


def test_run_event_append_list_and_summary(services):
    services.run_service.create_run("run1", thread_id="thread1", project_id="project1")
    artifact = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(
            run_id="run1",
            thread_id="thread1",
            project_id="project1",
            type=ArtifactType.report,
            content_text="summary",
            created_by_tool="test",
        ),
        PolicyContext(run_id="run1"),
    )
    approval = services.approval_store.create_approval_request(
        "export.create",
        "/exports",
        {"format": "csv"},
        PolicyContext(run_id="run1", thread_id="thread1", project_id="project1"),
    )

    first = services.run_service.append_event("run1", "node_start", "started", node_name="load")
    second = services.run_service.append_event(
        "run1",
        "tool_done",
        "registered",
        tool_name="artifact_register",
        artifact_ids=[artifact.artifact_id],
        approval_id=approval.approval_id,
    )

    events = services.run_service.list_events("run1")
    assert [event.event_id for event in events] == [first.event_id, second.event_id]
    assert events[1].artifact_ids == [artifact.artifact_id]

    summary = services.run_service.get_summary("run1")
    assert summary.run.run_id == "run1"
    assert [item.artifact_id for item in summary.artifacts] == [artifact.artifact_id]
    assert [item.approval_id for item in summary.pending_approvals] == [approval.approval_id]


def test_run_mcp_tools_return_tool_result_envelope(services):
    created = run_create_impl(services=services)
    assert created.ok is True
    assert created.data["run_id"].startswith("run_")
    assert created.data["status"] == "created"
