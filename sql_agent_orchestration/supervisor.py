from __future__ import annotations

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

    This is intentionally route-driven instead of a fixed serial chain. The
    parse_plan node chooses the required specialist agents, then the supervisor
    gates each handoff through central validation.
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
        self.agent_registry = {
            "sql_agent": self.sql_agent,
            "eda_agent": self.eda_agent,
            "analysis_agent": self.analysis_agent,
            "visualization_agent": self.visualization_agent,
            "report_agent": self.report_agent,
        }

    def run(self, user_query: str, *, thread_id: str | None = None) -> OrchestrationState:
        run = self.adapter.create_run(thread_id=thread_id, metadata={"entrypoint": "sql_agent_supervisor"})
        state = OrchestrationState(run_id=run.run_id, thread_id=thread_id, user_query=user_query)
        self.adapter.update_run_status(state.run_id, RunStatus.running)
        self.adapter.append_run_event(state.run_id, "supervisor.started", "Supervisor started.", node_name="start")

        try:
            self.parse_plan(state)
            for agent in self._agent_sequence(state):
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
        normalized = state.user_query.casefold()
        requires_mart = self._contains_any(
            normalized,
            "repeat",
            "reusable",
            "datamart",
            "mart",
            "save",
            "\ubc18\ubcf5",
            "\ub370\uc774\ud130\ub9c8\ud2b8",
            "\ub9c8\ud2b8",
            "\uc800\uc7a5",
            "\uc7ac\uc0ac\uc6a9",
        )
        wants_trend = self._contains_any(normalized, "trend", "monthly", "\uc6d4\ubcc4", "\ucd94\uc774")
        wants_eda = self._contains_any(
            normalized,
            "eda",
            "profile",
            "quality",
            "missing",
            "duplicate",
            "outlier",
            "distribution",
            "\ud488\uc9c8",
            "\uacb0\uce21",
            "\uc911\ubcf5",
            "\uc774\uc0c1\uce58",
            "\ubd84\ud3ec",
        )
        wants_analysis = wants_trend or self._contains_any(
            normalized,
            "analysis",
            "analyze",
            "insight",
            "hypothesis",
            "stat",
            "compare",
            "\ubd84\uc11d",
            "\uc778\uc0ac\uc774\ud2b8",
            "\uac00\uc124",
            "\ube44\uad50",
        )
        wants_visualization = wants_trend or self._contains_any(
            normalized,
            "chart",
            "visual",
            "visualization",
            "plot",
            "graph",
            "\ucc28\ud2b8",
            "\uc2dc\uac01\ud654",
            "\uadf8\ub798\ud504",
        )

        required_agents = ["sql_agent"]
        if wants_eda:
            required_agents.append("eda_agent")
        if wants_analysis:
            required_agents.append("analysis_agent")
        if wants_visualization:
            required_agents.append("visualization_agent")
        required_agents.append("report_agent")

        state.goal = "monthly trend analysis" if wants_trend else "SQL-backed response"
        state.plan = AnalysisPlan(
            goal=state.goal,
            metric="revenue" if self._contains_any(normalized, "revenue", "sales", "\ub9e4\ucd9c") else None,
            dimension="month" if wants_trend else None,
            requires_mart_review=requires_mart,
            required_agents=required_agents,
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

    def _agent_sequence(self, state: OrchestrationState) -> list[object]:
        requested = state.plan.required_agents if state.plan else ["sql_agent", "report_agent"]
        return [self.agent_registry[name] for name in requested if name in self.agent_registry]

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

    def _contains_any(self, value: str, *needles: str) -> bool:
        return any(needle in value for needle in needles)
