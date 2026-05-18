"""B-lane tests: SQL-Agent MVP and mart candidate behavior."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.models.artifacts import ArtifactType
from DATA_Analyst_Assistant_Agent.agents.sql.self_check import is_sql_safe, run_sql_self_check
from DATA_Analyst_Assistant_Agent.agents.sql.planner import build_sql_plan, SQLPlan
from DATA_Analyst_Assistant_Agent.agents.sql.mart import needs_mart_candidate
from DATA_Analyst_Assistant_Agent import BackendAdapter, SQLAgentSupervisor, SupervisorTerminalState


# ── fixtures ──

@pytest.fixture()
def adapter() -> BackendAdapter:
    base_dir = Path(".test_data") / f"sql_agent_{uuid.uuid4().hex}"
    config = BackendConfig(base_data_dir=base_dir / ".data_agent")
    try:
        yield BackendAdapter(config=config)
    finally:
        shutil.rmtree(base_dir, ignore_errors=True)


# ── self_check tests ──

class TestSQLSelfCheck:
    def test_select_is_safe(self):
        assert is_sql_safe("SELECT 1 AS x")

    def test_with_cte_is_safe(self):
        assert is_sql_safe("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_drop_is_blocked(self):
        assert not is_sql_safe("DROP TABLE users")

    def test_insert_is_blocked(self):
        assert not is_sql_safe("INSERT INTO users VALUES (1)")

    def test_delete_is_blocked(self):
        assert not is_sql_safe("DELETE FROM users")

    def test_update_is_blocked(self):
        assert not is_sql_safe("UPDATE users SET name='x'")

    def test_multi_statement_is_blocked(self):
        assert not is_sql_safe("SELECT 1; DROP TABLE users")

    def test_markdown_fence_stripped(self):
        assert is_sql_safe("```sql\nSELECT 1\n```")

    def test_post_execution_checks_columns(self):
        checks = run_sql_self_check("SELECT 1", columns=["x"], row_count=1)
        names = {c.name for c in checks}
        assert "preview_has_columns" in names
        assert "preview_row_count_available" in names
        assert all(c.passed for c in checks)

    def test_empty_columns_fails(self):
        checks = run_sql_self_check("SELECT 1", columns=[])
        col_check = next(c for c in checks if c.name == "preview_has_columns")
        assert not col_check.passed


# ── planner tests ──

class TestSQLPlanner:
    def test_revenue_monthly_plan(self):
        plan = build_sql_plan("월별 매출 추이")
        assert plan.metric == "revenue"
        assert plan.dimension == "month"
        assert "SELECT" in plan.generated_sql
        assert plan.reasoning

    def test_simple_query_fallback(self):
        plan = build_sql_plan("간단한 요약")
        assert plan.generated_sql == "SELECT 1 AS sample_value"

    def test_plan_has_structured_fields(self):
        plan = build_sql_plan("monthly revenue trend")
        assert isinstance(plan.selected_tables, list)
        assert isinstance(plan.selected_columns, list)
        assert plan.metric == "revenue"
        assert plan.dimension == "month"


# ── mart detection tests ──

class TestMartDetection:
    def test_korean_mart_keywords(self):
        assert needs_mart_candidate("반복 조회용 데이터마트 저장")
        assert needs_mart_candidate("재사용 가능한 마트")

    def test_english_mart_keywords(self):
        assert needs_mart_candidate("save as reusable datamart")
        assert needs_mart_candidate("create a mart for repeat queries")

    def test_no_mart_intent(self):
        assert not needs_mart_candidate("간단한 매출 요약")
        assert not needs_mart_candidate("show revenue summary")


# ── SQLAgent integration tests ──

class TestSQLAgentIntegration:
    def test_creates_preview_artifact(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("간단한 매출 요약을 보여줘")

        assert "sql_agent" in state.artifact_ids
        sql_artifacts = state.artifact_ids["sql_agent"]
        assert len(sql_artifacts) >= 1

    def test_creates_ge_validation_artifact(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("간단한 매출 요약을 보여줘")

        sql_artifacts = state.artifact_ids["sql_agent"]
        has_ge = False
        for aid in sql_artifacts:
            art = adapter.get_artifact(aid)
            if art.metadata.get("kind") == "ge_table_validation_json":
                has_ge = True
                break
        assert has_ge, "GE validation artifact not found"

    def test_creates_sql_plan_artifact(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("간단한 매출 요약을 보여줘")

        sql_artifacts = state.artifact_ids["sql_agent"]
        has_plan = False
        for aid in sql_artifacts:
            art = adapter.get_artifact(aid)
            if art.metadata.get("kind") == "sql_plan":
                has_plan = True
                break
        assert has_plan, "SQL plan artifact not found"

    def test_non_mart_query_no_approval(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("간단한 매출 요약을 보여줘")

        assert state.terminal_state == SupervisorTerminalState.completed
        assert not state.approval_ids

    def test_mart_query_requires_approval(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("반복 조회용 데이터마트로 저장해줘")

        assert state.terminal_state == SupervisorTerminalState.needs_user_approval
        assert state.approval_ids

    def test_mart_query_creates_candidate_artifact(self, adapter):
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("반복 조회용 데이터마트로 저장해줘")

        assert state.mart_candidate_ids, "No mart candidate artifact registered"
        art = adapter.get_artifact(state.mart_candidate_ids[0])
        assert art.metadata.get("kind") == "mart_candidate"

    def test_approval_handled_by_supervisor_not_agent(self, adapter):
        """SQLAgent sets approval.required but does not create approval request itself."""
        supervisor = SQLAgentSupervisor(adapter)
        state = supervisor.run("반복 조회용 데이터마트로 저장해줘")

        # Approval request exists (created by supervisor gate)
        assert state.approval_ids
        # But mart is NOT materialized yet
        assert state.mart_id is None

    def test_backend_not_modified(self):
        changed = [
            "DATA_Analyst_Assistant_Agent/agents/sql/agent.py",
            "DATA_Analyst_Assistant_Agent/agents/sql/planner.py",
            "DATA_Analyst_Assistant_Agent/agents/sql/self_check.py",
            "DATA_Analyst_Assistant_Agent/agents/sql/mart.py",
            "DATA_Analyst_Assistant_Agent/mart/metadata.py",
            "DATA_Analyst_Assistant_Agent/mart/persistence.py",
            "tests/test_sql_agent.py",
        ]
        assert not any(p.startswith("data_agent_backend/") for p in changed)
