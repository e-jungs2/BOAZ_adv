# ai agent 정의

# **전체 구조**

LangGraph는 전체 흐름과 상태를 관리하는 Main Supervisor 역할을 담당하고, LangChain은 각 Sub-Agent 내부 기능 구현에 사용한다.

```
User Query
→ Backend API
→ LangGraph Main Supervisor
→ Sub-Agents
→ Backend Storage / Artifact
→ temp_mart_db 또는 mart_db
→ Report / UI
```

## **데이터 저장 전략**

산출물은 목적에 따라 분리해서 저장한다.

```
LangGraph State
- 현재 실행에 필요한 최소 메타데이터

Backend DB / Artifact
- SQL문
- 실행 로그
- 검증 결과
- EDA 요약
- 분석 결과
- 차트 설정
- 최종 리포트

temp_mart_db
- 일시적 데이터마트

mart_db
- 사용자가 저장 선택한 반복 조회용 데이터마트

metadata_db
- mart_id
- owner
- source_sql
- schema_json
- refresh_policy
- created_at
```

## **데이터마트 저장 플로우**

```
SQL-Agent가 데이터마트 후보 생성
→ Validation Agent가 저장 가능성 검토
→ Main Supervisor가 사용자에게 저장 여부 제안
→ 사용자 선택
  → 일시적 사용: temp_mart_db 또는 artifact 저장
  → 반복 조회용 저장: mart_db 저장 + metadata_db 등록
```

## **핵심 원칙**

```
Main Supervisor가 전체 흐름을 제어한다.
Sub-Agent는 기능 단위로 분리한다.
각 Agent 내부에 self-check를 둔다.
중앙 Validation Agent가 전체 정합성을 검증한다.
State에는 데이터 전체를 넣지 않고 id와 metadata만 저장한다.
실제 데이터마트는 temp_mart_db와 mart_db로 분리한다.
원본 DB에는 절대 저장하지 않는다.
```

# Main-Agent (Planning)

Main Agent는 전체 흐름을 제어하는 Supervisor 역할을 한다. Planning은 별도 Sub-Agent로 빼기보다 Main Agent 내부 기능으로 두는 것이 적절하다.

```
Main Agent 역할
- 사용자 요청 해석
- 분석 목적 정의
- metric / dimension / filter 추출
- 필요한 Sub-Agent 호출 순서 결정
- 실패 시 재시도 또는 사용자 확인 판단
```

```
Main Agent 내부 Planning Node
→ parse_user_query
→ define_analysis_goal
→ extract_metric_dimension_filter
→ select_required_agents
→ create_execution_plan
```

# Sub-Agent 전략

큰 기능 단위는 Sub-Agent로 분리하고, 세부 로직은 각 Agent 내부 Node로 구성한다.

```
Main Supervisor
→ SQL-Agent
→ EDA-Agent
→ Analysis-Agent
→ Visualization-Agent
→ Report-Agent
```

각 Agent는 자체 검증 노드를 가지고, 중앙 Validation Agent가 단계별 결과를 다시 검증한다.

```
각 Agent 내부 self-check
→ 중앙 Validation Agent 검증
→ Main Supervisor가 다음 단계 결정
```

## Validation-Agent

Validation은 별도 Sub-Agent로 둔다.

각 Agent 내부에는 self-check 노드를 두고, 중앙 Validation Agent가 단계별 산출물을 2차 검증한다.

```
각 Sub-Agent 내부 self-check
→ Validation Agent
→ Main Agent가 다음 단계 결정
```

```
Main Agent
→ Planning
→ SQL-Agent
→ Validation-Agent
→ EDA-Agent
→ Validation-Agent
→ Analysis-Agent
→ Validation-Agent
→ Visualization-Agent
→ Validation-Agent
→ Report-Agent
```

정리하면:

```
Planning = Main Agent 내부
Validation = 별도 Sub-Agent
세부 검증 = 각 Agent 내부 self-check
전체 정합성 검증 = Validation Agent
```

## SQL-Agent

### **역할**

사용자 질문과 Planner 결과를 바탕으로 필요한 데이터를 조회하고, 분석용 데이터마트를 생성한다.

### **내부 Node**

```
load_schema
→ select_relevant_tables
→ generate_sql
→ validate_sql
→ execute_preview_sql
→ check_result_shape
→ propose_mart_storage
```

### **산출물**

```
generated_sql
selected_tables
selected_columns
preview_result
row_count
schema_info
mart_candidate
storage_recommendation
```

### **Backend**

```
backend DB / artifact
- generated_sql
- execution_log
- validation_result
- preview_result_artifact_id
- mart_metadata

state
- sql_artifact_id
- result_artifact_id
- mart_id
- row_count
- columns
```

### **저장 전략**

```
일회성 분석 → state 또는 temp_mart_db
반복 조회용 → mart_db
대용량 결과 → DB 저장, state에는 id만 저장
```

## EDA-Agent

### **역할**

SQL-Agent가 만든 결과 또는 데이터마트를 기반으로 데이터 품질과 분포를 확인한다.

### **내부 Node**

```
load_data_reference
→ profile_columns
→ check_missing_values
→ check_duplicates
→ check_distribution
→ detect_outliers
→ eda_self_check
```

### **산출물**

```
eda_summary
missing_value_report
duplicate_report
outlier_report
distribution_summary
data_quality_issues
recommended_analysis_path
```

### **Backend**

```
backend artifact
- eda_summary.json
- data_quality_report.json

state
- eda_summary_id
- data_quality_status
- key_issues
```

## 분석-Agent

### **역할**

EDA 결과를 반영해 실제 분석, 통계 검정, 세그먼트 비교, 인사이트 생성을 수행한다.

### **내부 Node**

```
select_analysis_method
→ run_analysis
→ statistical_check
→ segment_comparison
→ generate_insights
→ analysis_self_check
```

### **산출물**

```
analysis_result
statistical_result
segment_comparison
key_findings
limitations
insight_summary
```

### **Backend**

```
backend artifact
- analysis_result.json
- statistical_result.json
- insight_summary.json

state
- analysis_result_id
- key_findings
- limitations
```

## **Visualization-Agent**

### **역할**

분석 결과를 바탕으로 적절한 차트 유형을 선택하고 시각화 설정을 생성한다.

### **내부 Node**

```
select_chart_type
→ generate_chart_config
→ validate_axis_unit_label
→ render_chart_or_save_config
→ visualization_self_check
```

### **산출물**

```
chart_type
chart_config
chart_data_reference
chart_artifact_id
visualization_summary
```

### **Backend**

```
backend artifact
- chart_config.json
- chart_image 또는 chart_data

state
- chart_artifact_id
- chart_type
- chart_summary
```

## Report-Agent

### **역할**

모든 Agent의 산출물을 종합해 사용자에게 전달할 최종 리포트를 생성한다.

### **내부 Node**

```
collect_outputs
→ generate_report
→ check_consistency
→ add_limitations
→ final_report_validation
```

### **산출물**

```
final_report
summary
key_insights
charts
limitations
next_actions
```

### **Backend**

```
backend artifact
- final_report.md
- report_metadata.json

state
- report_artifact_id
- final_response
```