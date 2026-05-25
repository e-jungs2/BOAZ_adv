# Deep Interview Spec: 시스템 구조 간극 진단 & LLM 라우팅 정렬

## Metadata
- Interview ID: di-2026-05-25-llm-routing-alignment
- Rounds: 6
- Final Ambiguity Score: 28%
- Type: brownfield
- Generated: 2026-05-25
- Threshold: 20% (Success Criteria 차원이 사용자 의도로 보류되어 임계값 미달 — 의도된 조기 종료)
- Initial Context Summarized: no
- Status: BELOW_THRESHOLD_EARLY_EXIT (검증 차원 의도적 보류)

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.90 | 0.35 | 0.315 |
| Constraint Clarity | 0.85 | 0.25 | 0.213 |
| Success Criteria | 0.30 | 0.25 | 0.075 |
| Context Clarity | 0.80 | 0.15 | 0.120 |
| **Total Clarity** | | | **0.723** |
| **Ambiguity** | | | **0.277 (28%)** |

## 진단: "전체 구조가 생각과 다르다"는 느낌의 정체

사용자의 출발 질문은 "시스템 구조가 우리가 생각한 거랑 다른 것 같은데 어디가 다른지 모르겠다"였다.
코드 매핑(explore) 결과, 멘탈모델과 실제 구현 사이의 핵심 간극은 다음과 같다:

| # | 멘탈모델 (기대) | 실제 코드 | 이게 "진짜 어긋남"인가? |
|---|----------------|-----------|------------------------|
| 1 | LLM이 의도를 이해해 동적으로 라우팅 | `parse_plan`의 한·영 키워드 `if`문 매칭 (supervisor.py:103-136), LLM 미개입 | **예 — 1순위 정렬 대상** |
| 2 | 실제 스키마/테이블을 쿼리해 진짜 데이터 분석 | 모든 route의 SQL 템플릿이 `SELECT 1 AS ...` 합성 리터럴 (planner.py:72-92) | **아니오** — 백엔드 미완성 때문에 의도된 임시 상태. 나중에 채울 것 |
| 3 | `src/run_agent.py` / `src/sql_agent/` 진입점 | `src/` 디렉토리 없음. 실제는 `DATA_Analyst_Assistant_Agent/` 패키지 + `SQLAgentSupervisor` | 부분적 — 위치 인식 차이 (프로젝트 메모리 hot path와도 불일치) |
| 4 | architecture.md의 그래프(Route 노드, recovery_retry, NeedsClarification) | 실제 코드엔 없음. 명시적 노드 그래프만 존재 | 문서가 aspirational. 코드 정렬 후 문서 갱신 대상 |

**결론:** 느꼈던 "전반적 간극"의 본질은 *결정론적 키워드 스캐폴드 vs LLM 주도 에이전트*다. 다만 그 간극의 큰 조각(#2 합성 데이터)은 "틀린 것"이 아니라 "백엔드 미완성으로 아직 안 한 것"이다.

## Goal
실제 코드를 의도한 멘탈모델(LLM 주도 데이터 분석 에이전트)에 맞춰 정렬한다.
**1순위이자 이번 작업의 범위: `parse_plan`의 키워드 라우팅을 LLM 주도 라우팅으로 교체.**

## Constraints
- **최소 변경 원칙**: 명시적 노드 그래프(`run_sql_agent`, `run_eda_agent`, ...), `AgentEnvelope` 단방향 전달, `data_agent_backend`, 5개 route_kind는 **그대로 보존**.
- 교체 대상은 `parse_plan` 한 곳뿐. LLM 호출이 기존과 **동일한 출력**(`route_kind` + `remaining_agents` + `AnalysisPlan`)을 생산해야 함 — 다운스트림 인터페이스 불변.
- **백엔드 미완성**이 알려진 블로커. 실데이터 SQL 생성(planner.py `SELECT 1` 제거)은 **이번 범위 밖**, 백엔드 완료 후로 보류.
- 시퀀싱 고정: LLM 라우팅 먼저 → 실데이터는 나중.

## Non-Goals
- 합성 SQL 템플릿(`SELECT 1 AS ...`) 제거 / 실스키마 기반 SQL 생성 — **보류** (백엔드 의존).
- 그래프 구조를 동적 에이전트 루프로 재설계 — 보류 (현재는 명시적 노드 유지).
- `resume_after_approval`의 그래프 네이티브화 — 별개 이슈.
- architecture.md 다이어그램 정정 — 코드 정렬 후 후속.
- 진입점 경로 재구성(`src/` 신설 등) — 인식 차이일 뿐, 변경 불요.

## Acceptance Criteria
> ⚠️ 사용자가 **검증 방식을 의도적으로 보류**함. 실행 착수 시점에 확정 필요. 후보:
- [ ] (보류) route 결정 정확도: 골드셋 쿼리 → LLM이 고른 `route_kind`가 사람 기대와 일치 (특히 기존 키워드 매칭이 틀리던 쿼리)
- [ ] (보류) 회귀 방지: 기존 route별 테스트 스위트가 LLM 라우팅 교체 후에도 통과
- [ ] (보류) 의사결정 트레이스: LLM이 "왜 이 route인지" reasoning이 로그/아티팩트로 남음
- [x] 다운스트림 불변: `parse_plan` 교체 후 `remaining_agents`/`AnalysisPlan` 스키마가 기존과 호환 (이건 확정 기준)

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "합성 SQL은 잘못된 구현" | Round 4 Contrarian: 라우팅만 고치면 가짜 분석 아니냐? | 합성 SQL은 백엔드 미완성 탓 의도된 임시. 라우팅 먼저, 실데이터 나중 |
| "LLM 라우팅이 그냥 더 에이전트다워 보여서 1순위" | Round 4: 측정된 판단인가 직감인가? | 백엔드 의존성 때문에 실데이터가 오히려 나중. 라우팅이 먼저인 게 시퀀스상 맞음 |
| "그래프를 동적 루프로 재설계해야 함" | Round 6 Simplifier: 가장 작은 변경은? | parse_plan만 교체. 그래프 구조 보존 |

## Technical Context (brownfield)
- 실제 진입점: `DATA_Analyst_Assistant_Agent/__init__.py` → `SQLAgentSupervisor(adapter).run(query)`
- 라우팅 지점: `supervisor.py:98-166` `parse_plan()` — 그래프 첫 노드, 키워드 매칭으로 `route_kind` + `remaining_agents` 결정
- 5개 route: `simple`, `eda`, `trend`, `mart`, `comprehensive` → 각각 고정 에이전트 시퀀스
- 그래프 항상 `run_sql_agent` 먼저 실행 (graph.py:85, route 무관 무조건)
- route_kind 소비처: planner.py(템플릿 선택), analysis/methods.py, report/builder.py
- 교체 시 LLM은 `parse_plan`이 채우던 `state.route_kind`, `state.remaining_agents`, `AnalysisPlan`을 동일 계약으로 생산하면 됨

## Ontology (Key Entities)
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| SQLAgentSupervisor | core domain | route_kind, remaining_agents, agent_registry | invokes graph, runs all agents |
| parse_plan (Router) | core domain | keyword maps → route_kind | **교체 대상**; sets remaining_agents |
| Route (route_kind) | core domain | simple/eda/trend/mart/comprehensive | drives agent sequence + templates |
| SQLAgent | supporting | SQLPlan, templates | first node always; produces artifacts |
| Template | supporting | SELECT 1 literals | 보류 (백엔드 의존) |
| Backend (data_agent_backend) | external system | **미완성** | blocks real-data SQL |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 6 | 6 | - | - | N/A |
| 2 | 6 | 0 | 0 | 6 | 100% |
| 3 | 6 | 0 | 0 | 6 | 100% |
| 4 | 6 | 0 | 0 | 6 | 100% |
| 5 | 6 | 0 | 0 | 6 | 100% |
| 6 | 6 | 0 | 0 | 6 | 100% |

도메인 모델은 1라운드부터 완전 수렴 — 간극은 엔티티 정의가 아니라 "어느 엔티티의 구현이 멘탈모델과 다른가"에 있었음.

## Interview Transcript
<details>
<summary>Full Q&A (6 rounds)</summary>

### Round 1 — Goal | Ambiguity 100%→64%
**Q:** 멘탈모델과 어긋날 만한 4지점 중 어디가 "다르다"는 느낌에 가까운가? (다중)
**A:** 네 가지 모두 (SQL 합성 / 키워드 라우팅 / 진입점·구조 / 문서↔코드 불일치)

### Round 2 — Goal | 64%→56%
**Q:** 이 대화의 목적 — 어느 쪽을 진실로 삼을 것인가?
**A:** 코드를 멘탈모델로 (전향적 정렬)

### Round 3 — Goal | 56%→47%
**Q:** "의도한 시스템"의 핵심 정체성 한 가지?
**A:** LLM 주도 라우팅

### Round 4 — Constraints (Contrarian) | 47%→37%
**Q:** 라우팅만 고쳐도 SQL이 합성이면 가짜 분석 아닌가? 라우팅 먼저 vs 실데이터 먼저?
**A:** 백엔드 파트가 완료 안 됐으니 (실데이터는) 나중에 맞추는 게 맞다

### Round 5 — Success Criteria | 37%→35%
**Q:** 실데이터 없이 "라우팅 제대로 됐다"를 무엇으로 검증?
**A:** 검증 방법은 보류하고 싶음

### Round 6 — Constraints (Simplifier) | 35%→28%
**Q:** LLM 라우팅 넣을 때 교체 범위 — 어디까지?
**A:** parse_plan만 교체 (최소)

</details>
