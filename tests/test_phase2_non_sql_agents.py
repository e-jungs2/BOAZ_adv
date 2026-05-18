from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.artifacts import ArtifactType
from DATA_Analyst_Assistant_Agent import BackendAdapter, SQLAgentSupervisor, SupervisorTerminalState
from DATA_Analyst_Assistant_Agent.agents.analysis import AnalysisAgent
from DATA_Analyst_Assistant_Agent.agents.common import AgentRuntime


@pytest.fixture()
def adapter() -> BackendAdapter:
    base_dir = Path(".test_data") / f"phase2_c_{uuid.uuid4().hex}"
    config = BackendConfig(base_data_dir=base_dir / ".data_agent")
    try:
        yield BackendAdapter(config=config)
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


def artifact_text(adapter: BackendAdapter, artifact_id: str) -> str:
    artifact = adapter.get_artifact(artifact_id)
    assert artifact.local_path is not None
    return Path(artifact.local_path).read_text(encoding="utf-8")


def test_eda_profile_preview_includes_phase2_quality_fields(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("Profile data quality and missing values, then make a report.")

    eda_artifact = adapter.get_artifact(state.artifact_ids["eda_agent"][0])

    assert eda_artifact.type == ArtifactType.data_profile
    assert eda_artifact.preview["row_count"] >= 1
    assert eda_artifact.preview["columns"] == ["sample_value"]
    assert eda_artifact.preview["sample_available"] is True
    assert eda_artifact.preview["quality_status"] == "usable"
    assert eda_artifact.preview["key_issues"] == []
    assert eda_artifact.preview["recommended_next_steps"] == ["continue_to_analysis", "document_limitations"]


def test_analysis_uses_eda_profile_when_available(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("Profile data quality and missing values, then make a report.")

    envelope = AnalysisAgent().run(state, AgentRuntime(adapter))
    analysis_artifact = adapter.get_artifact(envelope.artifact_ids()[0])

    assert analysis_artifact.metadata["kind"] == "analysis_result"
    assert "EDA profile evidence was considered" in " ".join(analysis_artifact.preview["key_findings"])
    assert "EDA profile artifacts summarize data quality signals" in " ".join(analysis_artifact.preview["limitations"])


def test_trend_chart_config_includes_axis_and_references(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("Analyze monthly revenue trend with a chart.")

    chart_artifact = adapter.get_artifact(state.artifact_ids["visualization_agent"][0])
    chart_payload = artifact_text(adapter, chart_artifact.artifact_id)

    assert chart_artifact.preview["chart_type"] == "line"
    assert chart_artifact.preview["title"]
    assert chart_artifact.preview["encoding"]["x"]["unit"] == "unknown"
    assert chart_artifact.preview["encoding"]["y"]["unit"] == "unknown"
    assert chart_artifact.preview["data_reference"] == state.artifact_ids["sql_agent"]
    assert "unit_note" in chart_payload


def test_report_sections_and_evidence_include_upstream_artifacts(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("Analyze monthly revenue trend with a chart.")
    report = artifact_text(adapter, state.artifact_ids["report_agent"][0])

    for heading in ("## Summary", "## Key Findings", "## Evidence", "## Visuals", "## Limitations", "## Next Actions"):
        assert heading in report

    for agent_name in ("sql_agent", "analysis_agent", "visualization_agent"):
        for artifact_id in state.artifact_ids[agent_name]:
            assert f"- {agent_name}: {artifact_id}" in report


def test_mart_approval_waiting_flow_does_not_create_report(adapter: BackendAdapter) -> None:
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run("반복 조회용 데이터마트 저장을 제안해줘.")

    assert state.terminal_state == SupervisorTerminalState.needs_user_approval
    assert "report_agent" not in state.artifact_ids
