"""SQL 에이전트 프롬프트 빌더.

기존 `sql_agent/sql_agent.py` 노드에 인라인돼 있던 프롬프트 텍스트를 그대로 분리한 것.
텍스트는 원본과 1바이트도 다르지 않게 유지한다(동작 보존).
"""

from __future__ import annotations

import json

from DATA_Analyst_Assistant_Agent.agents.sql._runtime import ALLOWED_MART_SCHEMA, format_result_rows


def plan_prompt(state) -> str:
    return f"""
너는 MySQL 기반 SQL/데이터마트 설계 질문 분석기다.

사용자 질문:
{state['user_question']}

스키마 JSON:
{state['schema_text']}

정합성 점검 JSON:
{state['integrity_text']}

규칙:
- task_type은 반드시 query_answer 또는 data_mart_build 중 하나
- 사용자가 "데이터마트", "마트 생성", "집계 테이블", "요약 테이블", "분석용 테이블 생성" 의도를 가지면 data_mart_build
- requested_output은 sql_only / execute_and_answer / create_table 중 하나
- relevant_tables는 실제 존재하는 테이블만
- 질문에 없는 조건 임의 추가 금지
- 애매한 점은 ambiguity_note에 기록
- 반드시 JSON만 출력

출력 형식:
{{
  "original_question": "...",
  "question_type": "...",
  "task_type": "...",
  "requested_output": "...",
  "target_metric": "...",
  "dimensions": ["..."],
  "filters": ["..."],
  "time_condition": "... 또는 null",
  "relevant_tables": ["..."],
  "mart_name": "... 또는 null",
  "grain": "... 또는 null",
  "load_strategy": "... 또는 null",
  "ambiguity_note": "... 또는 null"
}}
"""


def mart_design_prompt(state) -> str:
    return f"""
너는 분석용 데이터마트 설계자다.

사용자 질문:
{state['user_question']}

질문 분석 결과:
{json.dumps(state['plan'], ensure_ascii=False, indent=2)}

스키마 JSON:
{state['schema_text']}

정합성 점검 JSON:
{state['integrity_text']}

설계 규칙:
- 분석에 재사용 가능한 데이터마트 기준으로 설계
- grain을 반드시 명확히 정의
- key_columns, dimension_columns, measure_columns를 분리
- target_schema는 "{ALLOWED_MART_SCHEMA}" 로 고정
- incremental이 자연스러우면 incremental_column 제안
- 질문에 없는 정의를 과도하게 추가하지 말고 reasoning에 근거 설명
- 반드시 JSON만 출력

출력 형식:
{{
  "mart_name": "...",
  "target_schema": "{ALLOWED_MART_SCHEMA}",
  "grain": "...",
  "source_tables": ["..."],
  "key_columns": ["..."],
  "measure_columns": ["..."],
  "dimension_columns": ["..."],
  "incremental_column": "... 또는 null",
  "load_strategy": "full_refresh 또는 incremental",
  "design_reasoning": "..."
}}
"""


def generate_mart_prompt(state, feedback: str) -> str:
    return f"""
너는 MySQL 데이터마트 생성 SQL 작성기다.

사용자 질문:
{state['user_question']}

질문 분석 결과:
{json.dumps(state['plan'], ensure_ascii=False, indent=2)}

마트 설계 결과:
{json.dumps(state.get('mart_design', {}), ensure_ascii=False, indent=2)}

스키마 JSON:
{state['schema_text']}

정합성 점검 JSON:
{state['integrity_text']}

이전 피드백:
{feedback if feedback else "없음"}

규칙:
- CREATE TABLE ... AS SELECT 또는 INSERT INTO ... SELECT 형태만 허용
- 타겟 스키마는 반드시 {ALLOWED_MART_SCHEMA}
- source는 실제 존재 테이블만 사용
- grain이 깨지지 않게 집계
- 모호한 기준은 reasoning에 명시
- precheck_sql에는 원천 데이터 건수/기간 확인용 SELECT
- postcheck_sql에는 생성 후 row_count / 중복 / null 점검용 SELECT
- DROP, ALTER, TRUNCATE 금지
- 반드시 JSON만 출력

출력 형식:
{{
  "sql": "...",
  "sql_type": "create_table_as 또는 insert_select",
  "target_table": "{ALLOWED_MART_SCHEMA}.xxx",
  "source_tables": ["..."],
  "columns_used": ["..."],
  "business_grain": "...",
  "precheck_sql": "SELECT ...",
  "postcheck_sql": "SELECT ...",
  "reasoning": "..."
}}
"""


def generate_query_prompt(state, feedback: str) -> str:
    return f"""
너는 MySQL 조회 SQL 작성기다.

사용자 질문:
{state['user_question']}

질문 분석 결과:
{json.dumps(state['plan'], ensure_ascii=False, indent=2)}

스키마 JSON:
{state['schema_text']}

정합성 점검 JSON:
{state['integrity_text']}

이전 피드백:
{feedback if feedback else "없음"}

규칙:
- MySQL SELECT SQL만 생성
- WITH 절 허용
- 질문에 없는 조건 임의 추가 금지
- 정합성 문제가 있는 컬럼/테이블 주의
- 반드시 JSON만 출력

출력 형식:
{{
  "sql": "SELECT ...",
  "sql_type": "select",
  "target_table": null,
  "source_tables": ["..."],
  "columns_used": ["..."],
  "business_grain": null,
  "precheck_sql": null,
  "postcheck_sql": null,
  "reasoning": "..."
}}
"""


def validate_prompt(state) -> str:
    return f"""
너는 SQL/데이터마트 검증기다.

사용자 질문:
{state['user_question']}

질문 분석 결과:
{json.dumps(state['plan'], ensure_ascii=False, indent=2)}

마트 설계 결과:
{json.dumps(state.get('mart_design', {}), ensure_ascii=False, indent=2)}

정합성 점검 JSON:
{state['integrity_text']}

생성된 SQL:
{state['sql_draft']['sql']}

SQL 설명:
{state['sql_draft']['reasoning']}

사전 점검 결과:
{format_result_rows(state.get('precheck_result'))}

실행 결과:
{format_result_rows(state['sql_result'])}

사후 점검 결과:
{format_result_rows(state.get('postcheck_result'))}

행 수:
{state['row_count']}

검증 규칙:
1. task_type=query_answer 이면 질문 조건 충족 여부 검증
2. task_type=data_mart_build 이면 grain 적합성, 타겟 테이블 적절성, 재사용성 검증
3. 질문에 없는 조건 추가면 invalid
4. 정합성 문제 무시하면 invalid
5. 반드시 JSON만 출력

출력 형식:
{{
  "result": "valid" 또는 "invalid",
  "reason": "...",
  "feedback": "..."
}}
"""


def finalize_mart_prompt(state) -> str:
    return f"""
너는 데이터 엔지니어/분석가용 결과 요약기다.

사용자 질문:
{state['user_question']}

마트 설계:
{json.dumps(state.get('mart_design', {}), ensure_ascii=False, indent=2)}

생성 SQL:
{state['sql_draft']['sql']}

사전 점검 결과:
{format_result_rows(state.get('precheck_result'))}

사후 점검 결과:
{format_result_rows(state.get('postcheck_result'))}

규칙:
- 한국어
- 마트명, grain, 적재 방식, 핵심 컬럼, 검증 결과를 짧게 요약
- 없는 내용 추측 금지
"""


def finalize_answer_prompt(state) -> str:
    return f"""
너는 데이터 분석 답변 작성기다.

사용자 질문:
{state['user_question']}

SQL 결과:
{format_result_rows(state['sql_result'], max_rows=20)}

규칙:
- 한국어
- 핵심 결과 먼저
- 없는 내용 추측 금지
- 결과 범위 안에서만 설명
"""


def finalize_rewrite_prompt(state, answer: str) -> str:
    return f"""
너는 데이터 분석 결과를 사용자에게 설명하는 한국어 분석가다.

사용자 질문:
{state['user_question']}

SQL 결과:
{format_result_rows(state['sql_result'], max_rows=20)}

초안 답변:
{answer}

다시 작성 규칙:
- 반드시 한국어로 작성한다.
- 마크다운 표를 절대 만들지 않는다.
- 결과 표는 최종 리포트의 SQL Result Table 섹션에서 따로 보여주므로, 여기서는 해석만 쓴다.
- 먼저 1~2문장으로 핵심 결과와 가장 중요한 해석을 설명한다.
- 그 다음 SQL 결과의 각 행을 "- **항목명**: 주요 수치..." 형식의 bullet 목록으로 정리해도 된다.
- bullet 목록에는 배송 지연율, 전체 주문 수, 배송 지연 주문 수, 평균 리뷰 점수를 포함한다.
- 마지막에 1문장으로 리뷰 점수와 배송 지연율 관계 또는 해석 시 주의점을 덧붙인다.
- 숫자는 SQL 결과에 있는 값만 사용한다.
- 마지막 문장은 "따라서"로 시작해 결론을 정리한다.
"""
