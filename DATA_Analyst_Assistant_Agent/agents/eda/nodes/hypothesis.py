"""hypothesis 노드 — 검증 가능한 가설 3개 + 다음 에이전트용 핸드오프 요약."""

from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.eda._runtime import append_errors, get_llm
from DATA_Analyst_Assistant_Agent.agents.eda.nodes.react import run_node_with_retry
from DATA_Analyst_Assistant_Agent.agents.eda.prompts import handoff_summary_prompt, hypothesis_prompt
from DATA_Analyst_Assistant_Agent.agents.eda.state import EDAState


def hypothesis_node(state: EDAState) -> dict:
    llm = get_llm()
    prompt = hypothesis_prompt(state["user_question"], state.get("insight_result", ""))
    fb = state.get("validation_feedback")
    if fb:
        prompt += f"\n[직전 검증 지적 — 반드시 보완하라]\n{fb}\n"
    hypotheses, err1 = run_node_with_retry(
        lambda: llm.invoke(prompt).content.strip(), "hypothesis", fallback="가설 생성 실패"
    )

    summary_prompt = handoff_summary_prompt(state.get("insight_result", ""), hypotheses)
    final_summary, err2 = run_node_with_retry(
        lambda: llm.invoke(summary_prompt).content.strip(), "final_summary", fallback="요약 생성 실패"
    )
    return {
        "hypotheses": hypotheses,
        "final_summary": final_summary,
        "error_log": append_errors(state, err1, err2),
    }
