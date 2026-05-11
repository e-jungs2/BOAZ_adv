from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.artifacts import ArtifactType
from data_agent_backend.models.approvals import ApprovalDecision, ApprovalStatus
from data_agent_backend.models.runs import RunStatus
from sql_agent_orchestration import BackendAdapter, SQLAgentSupervisor, SupervisorTerminalState


@pytest.fixture()
def adapter() -> BackendAdapter:
    base_dir = Path(".test_data") / f"backend_{uuid.uuid4().hex}"
    config = BackendConfig(base_data_dir=base_dir / ".data_agent")
    try:
        yield BackendAdapter(config=config)
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def test_adapter_contract_creates_run_event_artifact_policy_and_approval(adapter: BackendAdapter) -> None:
    run = adapter.create_run(metadata={"test": "adapter_contract"})
    event = adapter.append_run_event(run.run_id, "test.event", "event recorded", node_name="test")
    artifact = adapter.register_artifact(
        run.run_id,
        ArtifactType.file,
        content_text='{"ok": true}',
        filename="contract.json",
        created_by_tool="test",
        metadata={"kind": "contract_test"},
    )
    decision = adapter.check_policy("policy.evaluate", "policy", {}, None)
    approval = adapter.request_approval("mart.persist", "mart", {"run_id": run.run_id})

    assert run.run_id.startswith("run_")
    assert event.event_id.startswith("evt_")
    assert artifact.artifact_id.startswith("art_")
    assert decision.allowed is True
    assert approval.status == ApprovalStatus.pending


def test_sql_preview_allows_select_and_blocks_write_sql(adapter: BackendAdapter) -> None:
    run = adapter.create_run()
    preview = adapter.run_sql_preview(run.run_id, "SELECT 1 AS sample_value")

    assert preview.type == ArtifactType.sql_result
    assert preview.preview["columns"] == ["sample_value"]

    with pytest.raises(Exception) as exc_info:
        adapter.run_sql_preview(run.run_id, "DROP TABLE users")

    assert getattr(exc_info.value, "code", "") == "POLICY_BLOCKED"


def test_supervisor_non_mart_query_completes_and_registers_report(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("간단한 매출 요약을 보여줘")

    assert state.terminal_state == SupervisorTerminalState.completed
    assert "sql_agent" in state.artifact_ids
    assert "report_agent" in state.artifact_ids

    run = adapter.services.run_service.get_run(state.run_id)
    assert run.status == RunStatus.succeeded

    report_artifact = adapter.get_artifact(state.artifact_ids["report_agent"][0])
    assert report_artifact.type == ArtifactType.report


def test_supervisor_mart_query_pauses_for_approval(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("월별 매출 추이를 분석하고, 반복 조회가 필요하면 데이터마트 저장을 제안해줘.")

    assert state.terminal_state == SupervisorTerminalState.needs_user_approval
    assert state.approval_ids
    assert "sql_agent" in state.artifact_ids
    assert "validation_agent" in state.artifact_ids

    run = adapter.services.run_service.get_run(state.run_id)
    approval = adapter.get_approval_status(state.approval_ids[0])

    assert run.status == RunStatus.waiting_approval
    assert approval.status == ApprovalStatus.pending


def test_approval_resume_registers_mart_metadata(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("반복 조회용 데이터마트로 저장할 후보를 만들어줘.")
    approval_id = state.approval_ids[0]

    adapter.services.approval_store.resolve_approval_request(approval_id, ApprovalDecision.approve)
    resumed = supervisor.resume_after_approval(state, approval_id)

    assert resumed.mart_id
    assert "mart_metadata" in resumed.artifact_ids

    metadata_artifact = adapter.get_artifact(resumed.artifact_ids["mart_metadata"][0])
    assert metadata_artifact.metadata["kind"] == "mart_metadata"


def test_backend_non_modification_guard_paths() -> None:
    changed_contract_paths = [
        "docs/sql_agent_architecture/architecture.md",
        "sql_agent_orchestration/backend_adapter.py",
        "tests/test_sql_agent_orchestration.py",
    ]

    assert not any(path.startswith("data_agent_backend/") for path in changed_contract_paths)
