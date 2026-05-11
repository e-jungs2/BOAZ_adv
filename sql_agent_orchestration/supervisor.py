from __future__ import annotations

from collections.abc import Iterable

from data_agent_backend.models.approvals import ApprovalStatus
from data_agent_backend.models.runs import RunStatus

from sql_agent_orchestration.agents import (
    AgentRuntime,
    AnalysisAgent,
    CentralValidationAgent,
    EDAAgent,
    ReportAgent,
    SQLAgent,
    VisualizationAgent,
)
from sql_agent_orchestration.backend_adapter import BackendAdapter
from sql_agent_orchestration.models import (
    AgentEnvelope,
    AgentStatus,
    AnalysisPlan,
    OrchestrationState,
    SupervisorTerminalState,
)


class SQLAgentSupervisor:
    """Minimal LangGraph-compatible supervisor skeleton.

    The class intentionally keeps the orchestration decisions explicit and testable.
    A future LangGraph StateGraph can wrap these node methods without changing
    specialist agent contracts.
    """

    def __init__(
        self,
        adapter: BackendAdapter,
        *,
        sql_agent: SQLAgent | None = None,
        validation_agent: CentralValidationAgent | None = None,
        eda_agent: EDAAgent | None = None,
        analysis_agent: AnalysisAgent | None = None,
        visualization_agent: VisualizationAgent | None = None,
        report_agent: ReportAgent | None = None,
    ) -> None:
        self.adapter = adapter
        self.runtime = AgentRuntime(adapter)
        self.sql_agent = sql_agent or SQLAgent()
        self.validation_agent = validation_agent or CentralValidationAgent()
        self.eda_agent = eda_agent or EDAAgent()
        self.analysis_agent = analysis_agent or AnalysisAgent()
        self.visualization_agent = visualization_agent or VisualizationAgent()
        self.report_agent = report_agent or ReportAgent()

    def run(self, user_query: str, *, thread_id: str | None = None) -> OrchestrationState:
        run = self.adapter.create_run(thread_id=thread_id, metadata={"entrypoint": "sql_agent_supervisor"})
        state = OrchestrationState(run_id=run.run_id, thread_id=thread_id, user_query=user_query)
        self.adapter.update_run_status(state.run_id, RunStatus.running)
        self.adapter.append_run_event(state.run_id, "supervisor.started", "Supervisor started.", node_name="start")

        try:
            self.parse_plan(state)
            for agent in self._agent_sequence():
                state.current_step = agent.name
                self.adapter.append_run_event(state.run_id, "agent.started", f"{agent.name} started.", node_name=agent.name)
                envelope = agent.run(state, self.runtime)
                self._record_agent_result(state, envelope)

                validation = self.central_validate(state, envelope)
                self._record_agent_result(state, validation)
                gate = self.supervisor_gate(state, envelope, validation)
                if gate != "continue":
                    return state

            self.finalize(state)
            return state
        except Exception as exc:
            state.error_state = {"type": type(exc).__name__, "message": str(exc), "step": state.current_step}
            state.terminal_state = SupervisorTerminalState.failed_terminal
            self.adapter.append_run_event(
                state.run_id,
                "supervisor.failed",
                str(exc),
                node_name=state.current_step,
                metadata=state.error_state,
            )
            self.adapter.update_run_status(state.run_id, RunStatus.failed, metadata={"terminal_state": state.terminal_state.value})
            return state

    def parse_plan(self, state: OrchestrationState) -> None:
        query = state.user_query
        requires_mart = any(token in query for token in ("반복", "데이터마트", "마트", "저장", "재사용"))
        wants_trend = any(token in query for token in ("월별", "추이", "trend", "monthly"))
        state.goal = "월별 추이 분석" if wants_trend else "SQL 기반 질의 응답"
        state.plan = AnalysisPlan(
            goal=state.goal,
            metric="매출" if "매출" in query else None,
            dimension="월" if wants_trend else None,
            requires_mart_review=requires_mart,
            source_sql="SELECT 1 AS sample_value",
        )
        state.current_step = "parse_plan"
        self.adapter.append_run_event(
            state.run_id,
            "supervisor.plan_created",
            "Execution plan created.",
            node_name="parse_plan",
            metadata=state.plan.model_dump(mode="json"),
        )

    def central_validate(self, state: OrchestrationState, upstream: AgentEnvelope) -> AgentEnvelope:
        validation = self.validation_agent.run(state, self.runtime, upstream)
        state.validation_status = validation.status.value
        return validation

    def supervisor_gate(self, state: OrchestrationState, upstream: AgentEnvelope, validation: AgentEnvelope) -> str:
        if validation.status == AgentStatus.failed:
            if validation.retry_hint.retryable:
                state.terminal_state = SupervisorTerminalState.failed_with_recoverable_context
                self.adapter.update_run_status(
                    state.run_id,
                    RunStatus.failed,
                    metadata={"terminal_state": state.terminal_state.value, "retry_hint": validation.retry_hint.model_dump(mode="json")},
                )
                return "failed_with_recoverable_context"
            state.terminal_state = SupervisorTerminalState.failed_terminal
            self.adapter.update_run_status(state.run_id, RunStatus.failed, metadata={"terminal_state": state.terminal_state.value})
            return "failed_terminal"

        if upstream.approval.required or validation.approval.required:
            approval = self.adapter.request_approval(
                "mart.persist",
                "mart",
                {
                    "reason": upstream.approval.reason or validation.approval.reason,
                    "run_id": state.run_id,
                    "source_artifact_ids": upstream.artifact_ids(),
                    "plan": state.plan.model_dump(mode="json") if state.plan else {},
                },
            )
            state.approval_ids.append(approval.approval_id)
            state.terminal_state = SupervisorTerminalState.needs_user_approval
            state.current_step = "approval_gate"
            self.adapter.append_run_event(
                state.run_id,
                "approval.required",
                "Mart persistence requires approval.",
                node_name="approval_gate",
                approval_id=approval.approval_id,
            )
            self.adapter.update_run_status(
                state.run_id,
                RunStatus.waiting_approval,
                metadata={"terminal_state": state.terminal_state.value, "approval_id": approval.approval_id},
            )
            return "needs_user_approval"

        return "continue"

    def resume_after_approval(self, state: OrchestrationState, approval_id: str) -> OrchestrationState:
        approval = self.adapter.get_approval_status(approval_id)
        if approval.status != ApprovalStatus.approved:
            state.terminal_state = SupervisorTerminalState.failed_with_recoverable_context
            state.error_state = {"approval_id": approval_id, "approval_status": approval.status.value}
            return state

        source_artifact_id = next(iter(state.artifact_ids.get("sql_agent", [])), "unknown")
        mart_ref = self.adapter.materialize_mart_metadata(
            state.run_id,
            mart_id=f"mart_{state.run_id}",
            source_sql_artifact_id=source_artifact_id,
            approval_id=approval_id,
            schema_json={"columns": []},
            refresh_policy="manual",
        )
        state.mart_id = f"mart_{state.run_id}"
        state.add_artifacts("mart_metadata", [mart_ref.artifact_id])
        return state

    def finalize(self, state: OrchestrationState) -> None:
        state.current_step = "finalize"
        state.terminal_state = SupervisorTerminalState.completed
        self.adapter.append_run_event(state.run_id, "supervisor.completed", "Supervisor completed.", node_name="finalize")
        self.adapter.update_run_status(state.run_id, RunStatus.succeeded, metadata={"terminal_state": state.terminal_state.value})

    def _agent_sequence(self) -> Iterable[object]:
        return (self.sql_agent, self.eda_agent, self.analysis_agent, self.visualization_agent, self.report_agent)

    def _record_agent_result(self, state: OrchestrationState, envelope: AgentEnvelope) -> None:
        state.add_artifacts(envelope.agent_name, envelope.artifact_ids())
        self.adapter.append_run_event(
            state.run_id,
            "agent.completed",
            envelope.summary,
            node_name=envelope.agent_name,
            artifact_ids=envelope.artifact_ids(),
            metadata={
                "status": envelope.status.value,
                "next_handoff": envelope.next_handoff,
                "approval_required": envelope.approval.required,
            },
        )
