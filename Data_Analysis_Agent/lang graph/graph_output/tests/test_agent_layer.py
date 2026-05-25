from __future__ import annotations

import asyncio

import pytest

from data_agent_agent.config import DEFAULT_OPENAI_MODEL, AgentConfig, AgentConfigError
from data_agent_agent.deep_agent import load_system_prompt
from data_agent_agent.mcp_client import BackendMCPToolError, require_backend_tools
from data_agent_agent.runner import AgentRuntimeError, parse_args, resolve_datasource_id, run_cli
from data_agent_agent.runtime import AgentRunRequest, AgentRuntime, AgentRuntimeError as RuntimeAgentRuntimeError
from data_agent_agent.tool_provider import FunctionBackendToolProvider
from data_agent_agent.tools import build_agent_tools, normalize_tool_result


class FakeRawTool:
    def __init__(self, name, response, calls):
        self.name = name
        self.response = response
        self.calls = calls

    async def ainvoke(self, payload):
        self.calls.append((self.name, payload))
        return self.response


class FakeAgent:
    def __init__(self, events):
        self.events = events

    async def ainvoke(self, payload):
        self.events.append(("agent_invoke", payload))
        return {"messages": [{"role": "assistant", "content": "완료"}]}


def make_raw_tools(events, **overrides):
    raw_tools = {
        "run_create": FakeRawTool("run_create", {"ok": True, "data": {"run_id": "run_1"}, "error": None}, events),
        "datasource_list": FakeRawTool("datasource_list", {"ok": True, "data": [], "error": None}, events),
        "datasource_create": FakeRawTool("datasource_create", {"ok": True, "data": {"datasource_id": "ds_created"}, "error": None}, events),
        "datasource_test": FakeRawTool(
            "datasource_test",
            {"ok": True, "data": {"datasource_id": "ds_created", "ok": True, "message": "Connection succeeded."}, "error": None},
            events,
        ),
        "datasource_refresh_catalog": FakeRawTool("datasource_refresh_catalog", {"ok": True, "data": [], "error": None}, events),
        "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, events),
        "analysis_build_context": FakeRawTool("analysis_build_context", {"ok": True, "data": {}, "error": None}, events),
        "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, events),
        "sandbox_run_python": FakeRawTool(
            "sandbox_run_python",
            {
                "ok": True,
                "data": {
                    "execution_id": "exec_1",
                    "status": "success",
                    "exit_code": 0,
                    "stdout": "done\n",
                    "stderr": "",
                    "runtime_ms": 10,
                    "created_artifact_ids": ["art_chart", "art_log"],
                    "error_message": None,
                },
                "error": None,
            },
            events,
        ),
    }
    raw_tools.update(overrides)
    return raw_tools


def mysql_config(**overrides):
    values = {
        "openai_api_key": "test-key",
        "mysql_name": "local mysql",
        "mysql_host": "127.0.0.1",
        "mysql_port": 3306,
        "mysql_database": "analytics",
        "mysql_username": "reader",
        "mysql_password": "secret",
    }
    values.update(overrides)
    return AgentConfig(**values)


def test_format_cli_error_includes_bootstrap_step_and_suggestion():
    from data_agent_agent.runner import format_cli_error

    exc = RuntimeAgentRuntimeError(
        "datasource_test 실패: DATASOURCE_CONNECTION_ERROR - Datasource connection failed.",
        details={
            "bootstrap_step": "datasource_test",
            "suggestion": "Check credentials.",
            "retryable": True,
        },
    )

    message = format_cli_error(exc)

    assert "datasource_test" in message
    assert "Check credentials." in message
    assert "재시도 가능" in message


def test_agent_config_defaults_model_without_env_file(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    config = AgentConfig.from_env(load_env=False)

    assert config.openai_model == DEFAULT_OPENAI_MODEL
    assert config.default_row_limit == 1000


def test_agent_config_missing_api_key_has_clear_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(AgentConfigError, match="OPENAI_API_KEY"):
        AgentConfig.from_env(load_env=False)


def test_agent_config_reads_mysql_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATA_AGENT_MYSQL_NAME", "local mysql")
    monkeypatch.setenv("DATA_AGENT_MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("DATA_AGENT_MYSQL_PORT", "3306")
    monkeypatch.setenv("DATA_AGENT_MYSQL_DATABASE", "analytics")
    monkeypatch.setenv("DATA_AGENT_MYSQL_USERNAME", "reader")
    monkeypatch.setenv("DATA_AGENT_MYSQL_PASSWORD", "secret")

    config = AgentConfig.from_env(load_env=False)

    assert config.mysql_name == "local mysql"
    assert config.mysql_host == "127.0.0.1"
    assert config.mysql_port == 3306
    assert config.mysql_database == "analytics"
    assert config.mysql_username == "reader"
    assert config.mysql_password == "secret"


def test_mysql_create_payload_reports_missing_env_vars():
    config = mysql_config(mysql_host=None, mysql_password=None)

    with pytest.raises(AgentConfigError) as exc_info:
        config.mysql_create_payload()

    message = str(exc_info.value)
    assert "DATA_AGENT_MYSQL_HOST" in message
    assert "DATA_AGENT_MYSQL_PASSWORD" in message


def test_get_catalog_summary_injects_fixed_datasource_id():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool(
                "datasource_get_catalog_summary",
                {"ok": True, "data": {"table_count": 1}, "error": None},
                calls,
            ),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["get_catalog_summary"].ainvoke({})

        assert result == {"table_count": 1}
        assert calls == [("datasource_get_catalog_summary", {"datasource_id": "ds_1"})]

    asyncio.run(scenario())


def test_run_sql_injects_datasource_and_run_id():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool(
                "datasource_query",
                {
                    "ok": True,
                    "data": {
                        "artifact_ref": {"artifact_id": "art_1", "type": "sql_result"},
                        "columns": ["id"],
                        "row_count": 1,
                        "sample_rows": [{"id": 1}],
                    },
                    "error": None,
                },
                calls,
            ),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_sql"].ainvoke({"query": "select id from orders", "row_limit": 5})

        assert result["artifact_ref"]["artifact_id"] == "art_1"
        assert result["columns"] == ["id"]
        assert calls == [
            (
                "datasource_query",
                {
                    "datasource_id": "ds_1",
                    "query": "select id from orders",
                    "run_id": "run_1",
                    "row_limit": 5,
                },
            )
        ]

    asyncio.run(scenario())


def test_build_analysis_context_injects_fixed_datasource_id():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "analysis_build_context": FakeRawTool(
                "analysis_build_context",
                {
                    "ok": True,
                    "data": {
                        "datasource_id": "ds_1",
                        "question": "배송 지연 리뷰 점수",
                        "catalog_matches": [{"table_name": "orders"}],
                        "marts": [{"table_name": "mart_order_delivery"}],
                    },
                    "error": None,
                },
                calls,
            ),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["build_analysis_context"].ainvoke({"question": "배송 지연 리뷰 점수", "limit": 5})

        assert result["catalog_matches"][0]["table_name"] == "orders"
        assert result["marts"][0]["table_name"] == "mart_order_delivery"
        assert calls == [
            (
                "analysis_build_context",
                {
                    "datasource_id": "ds_1",
                    "question": "배송 지연 리뷰 점수",
                    "limit": 5,
                },
            )
        ]

    asyncio.run(scenario())


def test_run_sql_preserves_error_recovery_details():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool(
                "datasource_query",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "DATASOURCE_QUERY_ERROR",
                        "message": "Datasource query failed.",
                        "details": {
                            "suggestion": "Inspect the schema/catalog.",
                            "retryable": False,
                            "query_artifact_id": "art_query",
                        },
                    },
                },
                calls,
            ),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_sql"].ainvoke({"query": "select missing from orders", "row_limit": 0})

        assert result["ok"] is False
        assert result["code"] == "DATASOURCE_QUERY_ERROR"
        assert result["suggestion"] == "Inspect the schema/catalog."
        assert result["retryable"] is False
        assert result["query_artifact_id"] == "art_query"
        assert calls[0][1]["row_limit"] == 1000

    asyncio.run(scenario())


def test_run_python_injects_run_id_and_inputs():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool(
                "sandbox_run_python",
                {
                    "ok": True,
                    "data": {
                        "execution_id": "exec_1",
                        "status": "success",
                        "exit_code": 0,
                        "stdout": "ok\n",
                        "stderr": "",
                        "runtime_ms": 7,
                        "created_artifact_ids": ["art_2"],
                        "error_message": None,
                    },
                    "error": None,
                },
                calls,
            ),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_python"].ainvoke({"code": "print('ok')", "input_artifact_ids": ["art_1"]})

        assert result["status"] == "success"
        assert result["created_artifact_ids"] == ["art_2"]
        assert calls == [
            (
                "sandbox_run_python",
                {
                    "code": "print('ok')",
                    "run_id": "run_1",
                    "input_artifact_ids": ["art_1"],
                },
            )
        ]

    asyncio.run(scenario())


def test_run_python_uses_default_timeout_when_tool_timeout_missing():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
        }
        tools = {
            item.name: item
            for item in build_agent_tools(
                raw_tools,
                datasource_id="ds_1",
                run_id="run_1",
                default_python_timeout_ms=450000,
            )
        }

        await tools["run_python"].ainvoke({"code": "print('ok')"})

        assert calls == [
            (
                "sandbox_run_python",
                {
                    "code": "print('ok')",
                    "run_id": "run_1",
                    "input_artifact_ids": [],
                    "timeout_ms": 450000,
                },
            )
        ]

    asyncio.run(scenario())


def test_run_python_tool_schema_hides_timeout_ms_from_agent():
    calls = []
    raw_tools = {
        "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
        "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
        "sandbox_run_python": FakeRawTool("sandbox_run_python", {"ok": True, "data": {}, "error": None}, calls),
    }
    tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

    assert "timeout_ms" not in tools["run_python"].args


def test_run_python_preserves_backend_error_details():
    async def scenario():
        calls = []
        raw_tools = {
            "datasource_get_catalog_summary": FakeRawTool("datasource_get_catalog_summary", {"ok": True, "data": {}, "error": None}, calls),
            "datasource_query": FakeRawTool("datasource_query", {"ok": True, "data": {}, "error": None}, calls),
            "sandbox_run_python": FakeRawTool(
                "sandbox_run_python",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "POLICY_BLOCKED",
                        "message": "Blocked.",
                        "details": {"decision_id": "pd_1"},
                    },
                },
                calls,
            ),
        }
        tools = {item.name: item for item in build_agent_tools(raw_tools, datasource_id="ds_1", run_id="run_1")}

        result = await tools["run_python"].ainvoke({"code": "print('blocked')"})

        assert result["ok"] is False
        assert result["code"] == "POLICY_BLOCKED"
        assert result["message"] == "Blocked."
        assert result["details"] == {"decision_id": "pd_1"}

    asyncio.run(scenario())


def test_system_prompt_includes_python_retry_rule():
    prompt = load_system_prompt()

    assert "run_python" in prompt
    assert "최대 1회" in prompt
    assert "status=timeout" in prompt
    assert "자동 재시도하지" in prompt


def test_normalize_tool_result_parses_mcp_text_blocks():
    result = normalize_tool_result(
        [
            {
                "type": "text",
                "text": '{"ok": true, "data": {"datasource_id": "ds_1"}, "error": null}',
                "id": "lc_1",
            }
        ]
    )

    assert result == {"ok": True, "data": {"datasource_id": "ds_1"}, "error": None}


def test_normalize_tool_result_preserves_failure_envelope_dict():
    result = normalize_tool_result(
        {
            "ok": False,
            "data": None,
            "error": {
                "code": "POLICY_BLOCKED",
                "message": "Blocked.",
                "details": {"decision_id": "pd_1"},
            },
        }
    )

    assert result == {
        "ok": False,
        "data": None,
        "error": {
            "code": "POLICY_BLOCKED",
            "message": "Blocked.",
            "details": {"decision_id": "pd_1"},
        },
    }


def test_normalize_tool_result_handles_model_dump_object():
    class Dumpable:
        def model_dump(self, mode):
            assert mode == "json"
            return {"ok": True, "data": {"value": 1}, "error": None}

    assert normalize_tool_result(Dumpable()) == {"ok": True, "data": {"value": 1}, "error": None}


def test_normalize_tool_result_wraps_plain_string():
    assert normalize_tool_result("plain output") == {"ok": True, "data": "plain output", "error": None}


def test_cli_parser_parses_datasource_id_and_question():
    args = parse_args(["--datasource-id", "ds_1", "질문"])

    assert args.datasource_id == "ds_1"
    assert args.question == "질문"


def test_cli_parser_parses_python_timeout_ms():
    args = parse_args(["--python-timeout-ms", "450000", "질문"])

    assert args.python_timeout_ms == 450000
    assert args.question == "질문"


def test_cli_parser_allows_question_without_datasource_id():
    args = parse_args(["질문"])

    assert args.datasource_id is None
    assert args.question == "질문"


def test_run_create_is_called_before_agent_invoke():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        async def load_tools(_config):
            return raw_tools

        def make_agent(**_kwargs):
            return FakeAgent(events)

        result = await run_cli(
            datasource_id="ds_1",
            question="질문",
            config=AgentConfig(openai_api_key="test-key"),
            load_tools_func=load_tools,
            agent_factory=make_agent,
        )

        assert result.answer == "완료"
        assert result.run_id == "run_1"
        assert result.datasource_id == "ds_1"
        assert events[0][0] == "run_create"
        assert events[1][0] == "agent_invoke"
        assert events[0][1]["metadata"]["source"] == "data-agent-agent"
        assert events[0][1]["metadata"]["datasource_source"] == "cli"
        assert [event[0] for event in events if event[0].startswith("datasource_")] == []

    asyncio.run(scenario())


def test_run_metadata_includes_model_and_trace_name():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key", openai_model="gpt-test"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문", source="data-agent-api"))

        metadata = events[0][1]["metadata"]
        assert metadata["source"] == "data-agent-api"
        assert metadata["model"] == "gpt-test"
        assert metadata["trace_name"] == "data-agent:data-agent-api:ds_1:pending"

    asyncio.run(scenario())


def test_agent_runtime_uses_agent_runner_adapter():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        class FakeRunner:
            async def run(self, *, question, model, tools, metadata):
                events.append(
                    (
                        "runner_run",
                        {
                            "question": question,
                            "model": model,
                            "tool_names": [tool.name for tool in tools],
                            "metadata": metadata,
                        },
                    )
                )
                return {"answer": "adapter answer", "raw_result": {"adapter": True}}

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key", openai_model="gpt-test"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_runner=FakeRunner(),
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "adapter answer"
        assert result.raw_result == {"adapter": True}
        assert events[0][0] == "run_create"
        assert events[1][0] == "runner_run"
        assert events[1][1]["question"] == "질문"
        assert events[1][1]["model"] == "gpt-test"
        assert "run_sql" in events[1][1]["tool_names"]
        assert "run_python" in events[1][1]["tool_names"]
        assert events[1][1]["metadata"]["run_id"] == "run_1"
        assert events[1][1]["metadata"]["datasource_id"] == "ds_1"
        assert events[1][1]["metadata"]["trace_name"] == "data-agent:data-agent-agent:ds_1:run_1"

    asyncio.run(scenario())


def test_agent_runtime_passes_request_python_timeout_to_run_python_tool():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        class PythonRunner:
            async def run(self, *, question, model, tools, metadata):
                tool_by_name = {tool.name: tool for tool in tools}
                result = await tool_by_name["run_python"].ainvoke({"code": "print('ok')"})
                return {"answer": result["status"], "raw_result": result}

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_runner=PythonRunner(),
        )

        result = await runtime.run(
            AgentRunRequest(datasource_id="ds_1", question="질문", python_timeout_ms=450000)
        )

        assert result.answer == "success"
        assert events[-1] == (
            "sandbox_run_python",
            {
                "code": "print('ok')",
                "run_id": "run_1",
                "input_artifact_ids": [],
                "timeout_ms": 450000,
            },
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("python_timeout_ms", [0, 600001])
def test_agent_runtime_rejects_invalid_python_timeout_before_loading_tools(python_timeout_ms):
    async def scenario():
        calls = []

        async def load_tools(_config):
            calls.append("load_tools")
            return make_raw_tools(calls)

        class UnexpectedRunner:
            async def run(self, **_kwargs):
                calls.append("agent_run")
                return {"answer": "unexpected", "raw_result": {}}

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(load_tools),
            agent_runner=UnexpectedRunner(),
        )

        with pytest.raises(AgentConfigError, match="python_timeout_ms"):
            await runtime.run(
                AgentRunRequest(
                    datasource_id="ds_1",
                    question="질문",
                    python_timeout_ms=python_timeout_ms,
                )
            )

        assert calls == []

    asyncio.run(scenario())


def test_agent_runtime_rejects_bool_python_timeout_before_loading_tools():
    async def scenario():
        calls = []

        async def load_tools(_config):
            calls.append("load_tools")
            return make_raw_tools(calls)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(load_tools),
        )

        with pytest.raises(AgentConfigError, match="python_timeout_ms"):
            await runtime.run(
                AgentRunRequest(
                    datasource_id="ds_1",
                    question="질문",
                    python_timeout_ms=True,
                )
            )

        assert calls == []

    asyncio.run(scenario())


@pytest.mark.parametrize("python_timeout_ms", [0, 600001])
def test_run_cli_rejects_invalid_python_timeout_before_loading_tools(python_timeout_ms):
    async def scenario():
        calls = []

        async def load_tools(_config):
            calls.append("load_tools")
            return make_raw_tools(calls)

        with pytest.raises(AgentConfigError, match="python_timeout_ms"):
            await run_cli(
                datasource_id="ds_1",
                question="질문",
                python_timeout_ms=python_timeout_ms,
                config=AgentConfig(openai_api_key="test-key"),
                load_tools_func=load_tools,
                agent_factory=lambda **_kwargs: FakeAgent(calls),
            )

        assert calls == []

    asyncio.run(scenario())


def test_resolve_datasource_reuses_matching_env_datasource():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_list=FakeRawTool(
                "datasource_list",
                {
                    "ok": True,
                    "data": [
                        {
                            "datasource_id": "ds_existing",
                            "kind": "mysql",
                            "name": "local mysql",
                            "host": "127.0.0.1",
                            "port": 3306,
                            "database": "analytics",
                            "username": "reader",
                        }
                    ],
                    "error": None,
                },
                events,
            ),
        )

        datasource_id = await resolve_datasource_id(raw_tools, mysql_config(), None)

        assert datasource_id == "ds_existing"
        assert [event[0] for event in events] == ["datasource_list", "datasource_test", "datasource_refresh_catalog"]

    asyncio.run(scenario())


def test_resolve_datasource_creates_when_no_match():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        datasource_id = await resolve_datasource_id(raw_tools, mysql_config(), None)

        assert datasource_id == "ds_created"
        assert [event[0] for event in events] == [
            "datasource_list",
            "datasource_create",
            "datasource_test",
            "datasource_refresh_catalog",
        ]
        create_payload = events[1][1]
        assert create_payload["host"] == "127.0.0.1"
        assert create_payload["password"] == "secret"

    asyncio.run(scenario())


def test_resolve_datasource_test_failure_stops_before_refresh():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_test=FakeRawTool(
                "datasource_test",
                {
                    "ok": False,
                    "data": None,
                    "error": {"code": "DATASOURCE_CONNECTION_ERROR", "message": "connection failed"},
                },
                events,
            ),
        )

        with pytest.raises(AgentRuntimeError, match="datasource_test"):
            await resolve_datasource_id(raw_tools, mysql_config(), None)

        assert [event[0] for event in events] == ["datasource_list", "datasource_create", "datasource_test"]

    asyncio.run(scenario())


def test_resolve_datasource_refresh_failure_stops():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_refresh_catalog=FakeRawTool(
                "datasource_refresh_catalog",
                {
                    "ok": False,
                    "data": None,
                    "error": {"code": "DATASOURCE_CATALOG_ERROR", "message": "refresh failed"},
                },
                events,
            ),
        )

        with pytest.raises(AgentRuntimeError, match="datasource_refresh_catalog"):
            await resolve_datasource_id(raw_tools, mysql_config(), None)

        assert [event[0] for event in events] == [
            "datasource_list",
            "datasource_create",
            "datasource_test",
            "datasource_refresh_catalog",
        ]

    asyncio.run(scenario())


def test_datasource_bootstrap_error_includes_step_and_backend_details():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_refresh_catalog=FakeRawTool(
                "datasource_refresh_catalog",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "DATASOURCE_CATALOG_ERROR",
                        "message": "refresh failed",
                        "details": {"suggestion": "Check grants.", "retryable": True},
                    },
                },
                events,
            ),
        )

        with pytest.raises(RuntimeAgentRuntimeError) as exc_info:
            await resolve_datasource_id(raw_tools, mysql_config(), None)

        exc = exc_info.value
        assert "datasource_refresh_catalog 실패" in str(exc)
        assert exc.details == {
            "bootstrap_step": "datasource_refresh_catalog",
            "backend_code": "DATASOURCE_CATALOG_ERROR",
            "backend_message": "refresh failed",
            "suggestion": "Check grants.",
            "retryable": True,
        }

    asyncio.run(scenario())


def test_run_create_error_includes_bootstrap_step():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            run_create=FakeRawTool(
                "run_create",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "RUN_CREATE_FAILED",
                        "message": "run create failed",
                        "details": {"retryable": False},
                    },
                },
                events,
            ),
        )
        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        with pytest.raises(RuntimeAgentRuntimeError) as exc_info:
            await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert exc_info.value.details == {
            "bootstrap_step": "run_create",
            "backend_code": "RUN_CREATE_FAILED",
            "backend_message": "run create failed",
            "retryable": False,
        }

    asyncio.run(scenario())


def test_agent_runtime_preserves_backend_failure_details():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_refresh_catalog=FakeRawTool(
                "datasource_refresh_catalog",
                {
                    "ok": False,
                    "data": None,
                    "error": {
                        "code": "DATASOURCE_CATALOG_ERROR",
                        "message": "refresh failed",
                        "details": {
                            "suggestion": "Retry after checking permissions.",
                            "retryable": True,
                            "query_artifact_id": "art_1",
                        },
                    },
                },
                events,
            ),
        )
        runtime = AgentRuntime(
            config=mysql_config(),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        with pytest.raises(RuntimeAgentRuntimeError, match="datasource_refresh_catalog") as exc_info:
            await runtime.run(AgentRunRequest(question="질문"))

        assert exc_info.value.details == {
            "suggestion": "Retry after checking permissions.",
            "retryable": True,
            "query_artifact_id": "art_1",
            "backend_code": "DATASOURCE_CATALOG_ERROR",
            "backend_message": "refresh failed",
            "bootstrap_step": "datasource_refresh_catalog",
        }
        assert [event[0] for event in events] == [
            "datasource_list",
            "datasource_create",
            "datasource_test",
            "datasource_refresh_catalog",
        ]

    asyncio.run(scenario())


def test_run_cli_without_datasource_id_prepares_env_datasource_before_agent():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        async def load_tools(_config):
            return raw_tools

        def make_agent(**_kwargs):
            return FakeAgent(events)

        result = await run_cli(
            question="질문",
            config=mysql_config(),
            load_tools_func=load_tools,
            agent_factory=make_agent,
        )

        assert result.run_id == "run_1"
        assert result.datasource_id == "ds_created"
        assert [event[0] for event in events] == [
            "datasource_list",
            "datasource_create",
            "datasource_test",
            "datasource_refresh_catalog",
            "run_create",
            "agent_invoke",
        ]
        assert events[4][1]["metadata"]["datasource_id"] == "ds_created"
        assert events[4][1]["metadata"]["datasource_source"] == "env"

    asyncio.run(scenario())


def test_run_cli_with_explicit_datasource_does_not_parse_mysql_env(monkeypatch):
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        async def load_tools(_config):
            return raw_tools

        def make_agent(**_kwargs):
            return FakeAgent(events)

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("DATA_AGENT_MYSQL_PORT", "not-int")

        result = await run_cli(
            datasource_id="ds_1",
            question="질문",
            load_tools_func=load_tools,
            agent_factory=make_agent,
        )

        assert result.answer == "완료"
        assert result.datasource_id == "ds_1"
        assert [event[0] for event in events] == ["run_create", "agent_invoke"]

    asyncio.run(scenario())


def test_run_cli_without_datasource_id_requires_mysql_env():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        async def load_tools(_config):
            return raw_tools

        with pytest.raises(AgentConfigError, match="DATA_AGENT_MYSQL_HOST"):
            await run_cli(
                question="질문",
                config=mysql_config(mysql_host=None),
                load_tools_func=load_tools,
                agent_factory=lambda **_kwargs: FakeAgent(events),
            )

        assert events == []

    asyncio.run(scenario())


def test_missing_required_mcp_tool_reports_name():
    with pytest.raises(BackendMCPToolError, match="datasource_query"):
        require_backend_tools({"run_create": object(), "datasource_get_catalog_summary": object()})


def test_agent_layer_import_smoke():
    import data_agent_agent.config
    import data_agent_agent.deep_agent
    import data_agent_agent.runner
    import data_agent_agent.runtime
    import data_agent_agent.tool_provider
    import data_agent_agent.tools

    assert data_agent_agent.config.DEFAULT_OPENAI_MODEL == DEFAULT_OPENAI_MODEL


def test_agent_runtime_with_explicit_datasource_skips_datasource_prepare():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        def make_agent(**_kwargs):
            return FakeAgent(events)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=make_agent,
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "완료"
        assert result.run_id == "run_1"
        assert result.datasource_id == "ds_1"
        assert [event[0] for event in events] == ["run_create", "agent_invoke"]
        assert events[0][1]["metadata"]["source"] == "data-agent-agent"
        assert events[0][1]["metadata"]["datasource_source"] == "cli"
        assert events[0][1]["metadata"]["datasource_id"] == "ds_1"

    asyncio.run(scenario())


def test_agent_runtime_request_metadata_cannot_override_core_run_metadata():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        def make_agent(**_kwargs):
            return FakeAgent(events)

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=make_agent,
        )

        await runtime.run(
            AgentRunRequest(
                datasource_id="ds_1",
                question="질문",
                metadata={
                    "source": "user-source",
                    "datasource_source": "user-datasource-source",
                    "datasource_id": "user-datasource-id",
                    "question": "user-question",
                    "custom": "kept",
                },
            )
        )

        metadata = events[0][1]["metadata"]
        assert metadata["source"] == "data-agent-agent"
        assert metadata["datasource_source"] == "cli"
        assert metadata["datasource_id"] == "ds_1"
        assert metadata["question"] == "질문"
        assert metadata["custom"] == "kept"

    asyncio.run(scenario())


def test_agent_runtime_datasource_test_without_message_uses_korean_fallback():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(
            events,
            datasource_test=FakeRawTool(
                "datasource_test",
                {"ok": True, "data": {"datasource_id": "ds_created", "ok": False}, "error": None},
                events,
            ),
        )

        runtime = AgentRuntime(
            config=mysql_config(),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        with pytest.raises(RuntimeAgentRuntimeError, match="Datasource 연결 테스트에 실패했습니다."):
            await runtime.run(AgentRunRequest(question="질문"))

        assert [event[0] for event in events] == ["datasource_list", "datasource_create", "datasource_test"]

    asyncio.run(scenario())


def test_agent_runtime_with_explicit_datasource_ignores_malformed_mysql_env(monkeypatch):
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        runtime = AgentRuntime(
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FakeAgent(events),
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "완료"
        assert result.datasource_id == "ds_1"
        assert [event[0] for event in events] == ["run_create", "agent_invoke"]

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("DATA_AGENT_MYSQL_PORT", "not-int")

    asyncio.run(scenario())


def test_agent_runtime_awaits_future_agent_result():
    async def scenario():
        events = []
        raw_tools = make_raw_tools(events)

        class FutureAgent:
            def ainvoke(self, payload):
                events.append(("agent_invoke", payload))
                future = asyncio.Future()
                future.set_result({"messages": [{"role": "assistant", "content": "완료"}]})
                return future

        runtime = AgentRuntime(
            config=AgentConfig(openai_api_key="test-key"),
            tool_provider=FunctionBackendToolProvider(lambda _config: raw_tools),
            agent_factory=lambda **_kwargs: FutureAgent(),
        )

        result = await runtime.run(AgentRunRequest(datasource_id="ds_1", question="질문"))

        assert result.answer == "완료"
        assert result.raw_result == {"messages": [{"role": "assistant", "content": "완료"}]}

    asyncio.run(scenario())


def test_function_backend_tool_provider_awaits_async_loader():
    async def scenario():
        raw_tools = {"run_create": object()}

        async def load_tools(_config):
            return raw_tools

        provider = FunctionBackendToolProvider(load_tools)

        assert await provider.load_tools(AgentConfig(openai_api_key="test-key")) is raw_tools

    asyncio.run(scenario())


def test_in_process_backend_tool_provider_exposes_required_tools(services):
    async def scenario():
        from data_agent_agent.mcp_client import REQUIRED_BACKEND_TOOLS
        from data_agent_agent.tool_provider import InProcessBackendToolProvider

        provider = InProcessBackendToolProvider(services)
        raw_tools = await provider.load_tools(AgentConfig(openai_api_key="test-key"))

        assert REQUIRED_BACKEND_TOOLS <= set(raw_tools)
        result = await raw_tools["run_create"].ainvoke({"metadata": {"source": "test"}})
        assert result["ok"] is True
        assert result["data"]["run_id"].startswith("run_")

    asyncio.run(scenario())


def test_in_process_backend_tool_provider_ignores_payload_services(services):
    async def scenario():
        from data_agent_agent.tool_provider import InProcessBackendToolProvider

        provider = InProcessBackendToolProvider(services)
        raw_tools = await provider.load_tools(AgentConfig(openai_api_key="test-key"))

        result = await raw_tools["run_create"].ainvoke({"metadata": {"source": "test"}, "services": object()})

        assert result["ok"] is True
        assert result["data"]["run_id"].startswith("run_")

    asyncio.run(scenario())


def test_in_process_analysis_build_context_raw_tool_returns_tool_result_envelope(services):
    async def scenario():
        from data_agent_agent.tool_provider import InProcessBackendToolProvider

        provider = InProcessBackendToolProvider(services)
        raw_tools = await provider.load_tools(AgentConfig(openai_api_key="test-key"))

        result = await raw_tools["analysis_build_context"].ainvoke(
            {"datasource_id": "ds_missing", "question": "배송 지연 분석"}
        )

        assert result["ok"] is False
        assert result["data"] is None
        assert result["error"]["code"] == "NOT_FOUND"

    asyncio.run(scenario())
