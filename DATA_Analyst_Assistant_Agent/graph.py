from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from DATA_Analyst_Assistant_Agent.backend_adapter import BackendAdapter
from DATA_Analyst_Assistant_Agent.models import AgentEnvelope, OrchestrationState

if TYPE_CHECKING:
    from DATA_Analyst_Assistant_Agent.supervisor import SQLAgentSupervisor

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover - import-safe fallback
    END = "__end__"
    START = "__start__"
    StateGraph = None
    LANGGRAPH_AVAILABLE = False


class GraphExecutionState(TypedDict):
    state: OrchestrationState
    last_agent_result: AgentEnvelope | None
    last_validation_result: AgentEnvelope | None
    gate_result: str | None


class FallbackCompiledGraph:
    def __init__(self, supervisor: SQLAgentSupervisor) -> None:
        self.supervisor = supervisor

    def invoke(self, graph_state: GraphExecutionState) -> GraphExecutionState:
        graph_state = self.supervisor.parse_plan(graph_state)
        while True:
            graph_state = self.supervisor.call_next_agent(graph_state)
            graph_state = self.supervisor.central_validate(graph_state)
            graph_state = self.supervisor.supervisor_gate(graph_state)
            next_node = self.supervisor.route_after_gate(graph_state)
            if next_node == "call_next_agent":
                continue
            if next_node == "finalize":
                graph_state = self.supervisor.finalize(graph_state)
            return graph_state


def build_graph(adapter: BackendAdapter, *, supervisor: SQLAgentSupervisor | None = None):
    if supervisor is None:
        from DATA_Analyst_Assistant_Agent.supervisor import SQLAgentSupervisor

        supervisor = SQLAgentSupervisor(adapter, build_runtime_graph=False)

    if not LANGGRAPH_AVAILABLE or StateGraph is None:
        return FallbackCompiledGraph(supervisor)

    builder = StateGraph(GraphExecutionState)
    builder.add_node("parse_plan", supervisor.parse_plan)
    builder.add_node("call_next_agent", supervisor.call_next_agent)
    builder.add_node("central_validate", supervisor.central_validate)
    builder.add_node("supervisor_gate", supervisor.supervisor_gate)
    builder.add_node("finalize", supervisor.finalize)
    builder.add_edge(START, "parse_plan")
    builder.add_edge("parse_plan", "call_next_agent")
    builder.add_edge("call_next_agent", "central_validate")
    builder.add_edge("central_validate", "supervisor_gate")
    builder.add_conditional_edges(
        "supervisor_gate",
        supervisor.route_after_gate,
        {
            "call_next_agent": "call_next_agent",
            "finalize": "finalize",
            "end": END,
        },
    )
    builder.add_edge("finalize", END)
    return builder.compile()
