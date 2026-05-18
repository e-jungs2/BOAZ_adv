# BOAZ Adv - DATA Analyst Assistant Agent

This branch uses `DATA_Analyst_Assistant_Agent/` as the active implementation.

The goal of this package is to prove the SQL analysis orchestration contract:

```text
User query
-> DATA_Analyst_Assistant_Agent supervisor/graph
-> SQL / Validation / EDA / Analysis / Visualization / Report agents
-> BackendAdapter
-> data_agent_backend runs, artifacts, approvals, policy, execution, workspace
-> final report or approval pause
```

## Active Structure

```text
DATA_Analyst_Assistant_Agent/
- graph.py              # LangGraph graph builder with a fallback runtime
- supervisor.py         # top-level orchestration and routing
- backend_adapter.py    # only allowed path into data_agent_backend
- models.py             # OrchestrationState, AgentEnvelope, shared enums
- agents/               # specialist agents
- mart/                 # mart metadata and persistence helpers

data_agent_backend/
- fixed backend platform dependency
- do not edit for orchestration changes

docs/sql_agent_architecture/
- architecture, PRD, test spec, ADR

tests/
- orchestration, agent, adapter, approval, and smoke tests
```

The old implementation folders `sql_agent/`, `eda_agent/`, and `Data_Analysis_Agent/` are no longer part of the active orchestration branch.

## Current MVP

Implemented:

- metadata-only orchestration state
- common `AgentEnvelope` contract
- BackendAdapter boundary around `data_agent_backend`
- dynamic supervisor routing for simple, EDA/profile, trend/chart, and mart queries
- SQL preview artifact creation
- SQL self-check and mart candidate proposal
- central validation handoff
- approval-gated mart metadata registration
- EDA `data_profile` artifact
- analysis result artifact
- visualization chart config artifact
- final markdown report artifact
- test coverage for routing, artifacts, approvals, and backend non-modification guard

Not implemented yet:

- production LLM-based planning or SQL generation
- real catalog/schema-aware query generation
- full statistical EDA and analysis
- chart image rendering
- production mart materialization and refresh scheduling
- true parallel fan-out/fan-in between independent agents

## Run Tests

Use the project virtual environment:

```powershell
cd C:\Users\yeon0\OneDrive\Desktop\adv\BOAZ_adv
.\.venv\Scripts\activate
python -m pytest tests -q
```

If Windows temp permissions cause pytest issues, run with a local temp directory:

```powershell
$env:TMP = "$PWD\.pytest_tmp"
$env:TEMP = "$PWD\.pytest_tmp"
python -m pytest tests -q
```

## Quick Smoke Run

```powershell
python -c "from DATA_Analyst_Assistant_Agent import BackendAdapter, SQLAgentSupervisor; s=SQLAgentSupervisor(BackendAdapter()); r=s.run('Analyze monthly revenue trend with a chart.'); print(r.terminal_state); print(r.artifact_ids)"
```

Expected result:

- terminal state is completed
- SQL, analysis, visualization, validation, and report artifacts are registered
- backend writes go through `BackendAdapter`

## Development Rules

- Do not modify `data_agent_backend/` for orchestration work.
- All backend interactions must go through `DATA_Analyst_Assistant_Agent/backend_adapter.py`.
- Keep `OrchestrationState` lean: IDs and small metadata only.
- All specialist agents must return `AgentEnvelope`.
- Store large outputs as backend artifacts, not in graph state.
- Mart persistence must pass through approval flow before durable registration.

