"""SQL 에이전트 LangGraph 노드 함수.

기존 `sql_agent/sql_agent.py` 의 노드들을 분리한 것. 프롬프트는 `prompts` 모듈,
헬퍼/엔진/LLM 은 `_runtime` 모듈, 상태/모델은 `state` 모듈에서 가져온다.
프롬프트·로직은 원본과 동일하게 유지(동작 보존).
"""

from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.sql import prompts
from DATA_Analyst_Assistant_Agent.agents.sql._runtime import (
    clean_sql,
    get_llm,
    is_safe_mart_sql,
    is_safe_query_sql,
    run_sql_commit,
    run_sql_fetchall,
    safe_json_parse,
)
from DATA_Analyst_Assistant_Agent.agents.sql.state import (
    AgentState,
    MartDesign,
    QuestionPlan,
    SQLDraft,
    ValidationResult,
)
from DATA_Analyst_Assistant_Agent.agents.sql.validator.integrity_loader import load_all_metadata
from DATA_Analyst_Assistant_Agent.agents.sql._runtime import ALLOWED_MART_SCHEMA


def load_context(state: AgentState):
    metadata = load_all_metadata()
    return {
        "schema_text": metadata["schema_text"],
        "integrity_text": metadata["integrity_text"],
    }


def plan_question(state: AgentState):
    response = get_llm().invoke(prompts.plan_prompt(state)).content

    fallback = QuestionPlan(
        original_question=state["user_question"],
        question_type="unknown",
        task_type="query_answer",
        requested_output="execute_and_answer",
        target_metric="unknown",
        dimensions=[],
        filters=[],
        time_condition=None,
        relevant_tables=[],
        mart_name=None,
        grain=None,
        load_strategy=None,
        ambiguity_note="질문 분석 파싱 실패"
    ).model_dump()

    parsed = safe_json_parse(response, fallback)
    parsed["original_question"] = state["user_question"]

    return {"plan": parsed}


def design_mart(state: AgentState):
    if state["plan"].get("task_type") != "data_mart_build":
        return {"mart_design": {}}

    response = get_llm().invoke(prompts.mart_design_prompt(state)).content

    fallback = MartDesign(
        mart_name=state["plan"].get("mart_name") or "mart_unknown",
        target_schema=ALLOWED_MART_SCHEMA,
        grain=state["plan"].get("grain") or "grain 미정",
        source_tables=state["plan"].get("relevant_tables", []),
        key_columns=[],
        measure_columns=[],
        dimension_columns=[],
        incremental_column=None,
        load_strategy=state["plan"].get("load_strategy") or "full_refresh",
        design_reasoning="마트 설계 파싱 실패"
    ).model_dump()

    parsed = safe_json_parse(response, fallback)
    return {"mart_design": parsed}


def generate_sql(state: AgentState):
    feedback = state.get("feedback", "").strip()
    task_type = state["plan"].get("task_type", "query_answer")

    if task_type == "data_mart_build":
        prompt = prompts.generate_mart_prompt(state, feedback)
    else:
        prompt = prompts.generate_query_prompt(state, feedback)

    response = get_llm().invoke(prompt).content

    fallback = SQLDraft(
        sql="SELECT 1;",
        sql_type="select",
        target_table=None,
        source_tables=[],
        columns_used=[],
        business_grain=None,
        precheck_sql=None,
        postcheck_sql=None,
        reasoning="SQL 생성 파싱 실패"
    ).model_dump()

    parsed = safe_json_parse(response, fallback)
    parsed["sql"] = clean_sql(parsed.get("sql", "SELECT 1;"))

    if parsed.get("precheck_sql"):
        parsed["precheck_sql"] = clean_sql(parsed["precheck_sql"])
    if parsed.get("postcheck_sql"):
        parsed["postcheck_sql"] = clean_sql(parsed["postcheck_sql"])

    return {"sql_draft": parsed}


def execute_sql(state: AgentState):
    sql = state["sql_draft"]["sql"].strip()
    sql_type = state["sql_draft"].get("sql_type", "select")
    target_table = state["sql_draft"].get("target_table")

    try:
        pre_rows = None
        if state["sql_draft"].get("precheck_sql"):
            pre_rows = run_sql_fetchall(state["sql_draft"]["precheck_sql"])

        if sql_type == "select":
            if not is_safe_query_sql(sql):
                return {
                    "sql_result": None,
                    "row_count": 0,
                    "precheck_result": pre_rows,
                    "postcheck_result": None,
                    "error": "조회 SQL 안전성 검사 실패"
                }

            rows = run_sql_fetchall(sql)

            return {
                "sql_result": rows,
                "row_count": len(rows),
                "precheck_result": pre_rows,
                "postcheck_result": None,
                "error": ""
            }

        ok, reason = is_safe_mart_sql(sql, target_table)
        if not ok:
            return {
                "sql_result": None,
                "row_count": 0,
                "precheck_result": pre_rows,
                "postcheck_result": None,
                "error": reason
            }

        run_sql_commit(sql)

        post_rows = None
        if state["sql_draft"].get("postcheck_sql"):
            post_rows = run_sql_fetchall(state["sql_draft"]["postcheck_sql"])

        return {
            "sql_result": [("마트 생성 완료", target_table)],
            "row_count": 1,
            "precheck_result": pre_rows,
            "postcheck_result": post_rows,
            "error": ""
        }

    except Exception as e:
        return {
            "sql_result": None,
            "row_count": 0,
            "precheck_result": None,
            "postcheck_result": None,
            "error": str(e)
        }


def validate_sql_and_result(state: AgentState):
    if state.get("error"):
        parsed = ValidationResult(
            result="invalid",
            reason=f"SQL 실행 오류: {state['error']}",
            feedback="실행 오류를 해결하고 task_type에 맞는 MySQL SQL로 다시 생성하라."
        ).model_dump()
        return {"validation": parsed, "feedback": parsed["feedback"]}

    response = get_llm().invoke(prompts.validate_prompt(state)).content

    fallback = ValidationResult(
        result="invalid",
        reason="검증 결과 파싱 실패",
        feedback="질문 조건, grain, 정합성 점검 내용을 반영해 다시 SQL을 생성하라."
    ).model_dump()

    parsed = safe_json_parse(response, fallback)
    return {"validation": parsed, "feedback": parsed.get("feedback", "")}


def finalize_answer(state: AgentState):
    if state["validation"].get("result") != "valid":
        return {
            "final_answer": (
                "검증 실패\n"
                f"사유: {state['validation'].get('reason')}\n"
                f"마지막 SQL: {state['sql_draft'].get('sql')}"
            )
        }

    if state["plan"].get("task_type") == "data_mart_build":
        answer = get_llm().invoke(prompts.finalize_mart_prompt(state)).content.strip()
        return {"final_answer": answer}

    answer = get_llm().invoke(prompts.finalize_answer_prompt(state)).content.strip()
    if _looks_like_markdown_table(answer):
        answer = get_llm().invoke(prompts.finalize_rewrite_prompt(state, answer)).content.strip()
    return {"final_answer": answer}


def _looks_like_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    separator_lines = [line for line in table_lines if set(line.replace("|", "").strip()) <= {"-", ":"}]
    return len(table_lines) >= 3 and bool(separator_lines)


def increase_retry(state: AgentState):
    return {"retry_count": state["retry_count"] + 1}
