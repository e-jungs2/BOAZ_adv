# Analysis Context MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Backend analysis context tools so an Agent can retrieve relevant catalog, profile, semantic, mart, and join candidates before generating SQL.

**Architecture:** Add focused models and services for profile storage, semantic registry, and analysis context assembly. Expose them through MCP and HTTP routes, then wire DeepAgent tools to call the new context endpoint before SQL generation.

**Tech Stack:** Python 3.11, Pydantic, SQLite, FastAPI, FastMCP, pytest, DeepAgents/LangChain tools.

---

## File Structure

- Create `src/data_agent_backend/models/analysis_context.py` for new request/response domain models.
- Create `src/data_agent_backend/services/analysis_profile_store.py` for table/column profile persistence.
- Create `src/data_agent_backend/services/semantic_registry.py` for metrics, terms, marts, and join paths.
- Create `src/data_agent_backend/services/analysis_context_service.py` for search and context assembly.
- Create `src/data_agent_backend/mcp/tools_analysis_context.py` for MCP tools.
- Create `src/data_agent_backend/api/routes_analysis_context.py` for HTTP endpoints.
- Modify `src/data_agent_backend/storage/migrations.py` to add SQLite tables.
- Modify `src/data_agent_backend/services/factory.py` to wire services.
- Modify `src/data_agent_backend/mcp/server.py` and `src/data_agent_backend/api/app.py` to register tools/routes.
- Modify `src/data_agent_agent/tools.py` and `src/data_agent_agent/prompts/system.md` to expose the new context flow to DeepAgent.
- Add tests in `tests/test_analysis_context.py` and extend `tests/test_agent_layer.py`.

### Task 1: Backend Analysis Context Tests

**Files:**
- Create: `tests/test_analysis_context.py`

- [ ] **Step 1: Write failing service tests**

Add tests that create a datasource catalog, upsert profiles and semantic records, then assert `build_analysis_context()` returns catalog matches, table profiles, metrics, marts, and join paths.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_analysis_context.py -q`

Expected: import or attribute failure because analysis context modules do not exist yet.

### Task 2: Models and SQLite Migration

**Files:**
- Create: `src/data_agent_backend/models/analysis_context.py`
- Modify: `src/data_agent_backend/models/__init__.py`
- Modify: `src/data_agent_backend/storage/migrations.py`

- [ ] **Step 1: Implement Pydantic models**

Define models for `CatalogSearchMatch`, `TableProfile`, `ColumnProfile`, `MetricDefinition`, `BusinessTerm`, `MartDefinition`, `JoinPath`, `SemanticSearchResult`, and `AnalysisContext`.

- [ ] **Step 2: Add migration version 4**

Create tables for table profiles, column profiles, semantic metrics, semantic terms, semantic marts, and semantic join paths with datasource scoped indexes.

- [ ] **Step 3: Run model/migration tests**

Run: `uv run pytest tests/test_analysis_context.py -q`

Expected: failures move from missing imports to missing service methods.

### Task 3: Profile and Semantic Services

**Files:**
- Create: `src/data_agent_backend/services/analysis_profile_store.py`
- Create: `src/data_agent_backend/services/semantic_registry.py`
- Modify: `src/data_agent_backend/services/factory.py`

- [ ] **Step 1: Implement profile upsert/get/list**

Support table and column profile upsert, lookup by table/column, and list by datasource.

- [ ] **Step 2: Implement semantic registry upsert/search/list**

Support metrics, business terms, marts, and join paths. Search starts as case-insensitive keyword matching over names, descriptions, tables, columns, and metrics.

- [ ] **Step 3: Wire services in factory**

Add `analysis_profile_store`, `semantic_registry`, and `analysis_context_service` fields to `BackendServices`.

### Task 4: Analysis Context Service

**Files:**
- Create: `src/data_agent_backend/services/analysis_context_service.py`

- [ ] **Step 1: Implement `catalog_search`**

Search existing datasource catalog by table name, column name, schema name, and metadata text. Return table grouped matches with reason and confidence.

- [ ] **Step 2: Implement `build_analysis_context`**

Combine catalog matches, available table/column profiles, semantic search hits, mart candidates, and join paths for matched tables.

- [ ] **Step 3: Run service tests**

Run: `uv run pytest tests/test_analysis_context.py -q`

Expected: service tests pass.

### Task 5: MCP and HTTP API

**Files:**
- Create: `src/data_agent_backend/mcp/tools_analysis_context.py`
- Create: `src/data_agent_backend/api/routes_analysis_context.py`
- Modify: `src/data_agent_backend/mcp/server.py`
- Modify: `src/data_agent_backend/api/app.py`
- Modify: `tests/test_analysis_context.py`

- [ ] **Step 1: Add MCP tool tests**

Test `analysis_build_context` and profile/semantic upsert tools return `ToolResult`.

- [ ] **Step 2: Add API route tests**

Use `TestClient` to call analysis context endpoints.

- [ ] **Step 3: Implement wrappers and route registration**

Expose the service methods through MCP and HTTP.

### Task 6: DeepAgent Tooling

**Files:**
- Modify: `src/data_agent_agent/tools.py`
- Modify: `src/data_agent_agent/prompts/system.md`
- Modify: `tests/test_agent_layer.py`

- [ ] **Step 1: Write failing agent tool tests**

Assert `build_analysis_context` is included when raw backend tools provide `analysis_build_context`.

- [ ] **Step 2: Implement Agent tool wrapper**

Expose an async LangChain tool that calls `analysis_build_context` with datasource id and question.

- [ ] **Step 3: Update prompt**

Tell the Agent to call `build_analysis_context(question)` before writing SQL.

### Task 7: Verification and Commit

**Files:**
- All changed files

- [ ] **Step 1: Run full tests**

Run: `uv run pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Inspect git diff**

Run: `git status --short --branch` and `git diff --stat`.

- [ ] **Step 3: Commit**

Commit message: `Add analysis context backend MVP`

