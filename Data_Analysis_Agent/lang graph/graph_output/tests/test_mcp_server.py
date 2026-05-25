from __future__ import annotations

import inspect

import pytest

from data_agent_backend.mcp import tools_approvals
from data_agent_backend.mcp import tools_analysis_context
from data_agent_backend.mcp import tools_artifacts
from data_agent_backend.mcp import tools_catalog
from data_agent_backend.mcp import tools_datasources
from data_agent_backend.mcp import tools_execution
from data_agent_backend.mcp import tools_exports
from data_agent_backend.mcp import tools_memory
from data_agent_backend.mcp import tools_policy
from data_agent_backend.mcp import tools_runs
from data_agent_backend.mcp import tools_workspace
from data_agent_backend.mcp.server import _mcp_public_tool, create_mcp_server
from data_agent_backend.mcp.tools_analysis_context import analysis_upsert_table_profile
from data_agent_backend.mcp.tools_datasources import datasource_create


PUBLIC_TOOL_FUNCTIONS = [
    tools_workspace.workspace_list,
    tools_workspace.workspace_read_text,
    tools_workspace.workspace_write_text,
    tools_workspace.workspace_preview,
    tools_runs.run_create,
    tools_runs.run_get,
    tools_runs.run_list,
    tools_runs.run_update_status,
    tools_runs.run_append_event,
    tools_runs.run_list_events,
    tools_runs.run_summary,
    tools_artifacts.artifact_register,
    tools_artifacts.artifact_get,
    tools_artifacts.artifact_list,
    tools_artifacts.artifact_preview,
    tools_artifacts.artifact_lineage,
    tools_memory.memory_propose,
    tools_memory.memory_list,
    tools_memory.memory_get,
    tools_memory.memory_search,
    tools_approvals.approval_list_pending,
    tools_approvals.approval_get,
    tools_approvals.approval_resolve,
    tools_policy.policy_evaluate,
    tools_execution.sql_run_query,
    tools_execution.sandbox_run_python,
    tools_catalog.catalog_list,
    tools_catalog.catalog_get,
    tools_datasources.datasource_create,
    tools_datasources.datasource_test,
    tools_datasources.datasource_list,
    tools_datasources.datasource_refresh_catalog,
    tools_datasources.datasource_get_catalog,
    tools_datasources.datasource_get_catalog_summary,
    tools_datasources.datasource_query,
    tools_exports.export_create,
]


ANALYSIS_CONTEXT_PUBLIC_TOOL_FUNCTIONS = [
    tools_analysis_context.analysis_catalog_search,
    tools_analysis_context.analysis_get_table_profile,
    tools_analysis_context.analysis_get_column_profile,
    tools_analysis_context.analysis_semantic_search,
    tools_analysis_context.analysis_get_join_paths,
    tools_analysis_context.analysis_build_context,
    tools_analysis_context.analysis_profile_datasource,
    tools_analysis_context.analysis_load_semantic_seed,
    tools_analysis_context.analysis_upsert_table_profile,
    tools_analysis_context.analysis_upsert_column_profile,
    tools_analysis_context.analysis_upsert_metric,
    tools_analysis_context.analysis_upsert_business_term,
    tools_analysis_context.analysis_upsert_mart,
    tools_analysis_context.analysis_upsert_join_path,
]


def test_public_mcp_tool_signatures_hide_internal_services_parameter():
    offenders = [
        fn.__name__
        for fn in PUBLIC_TOOL_FUNCTIONS
        if "services" in inspect.signature(fn).parameters
    ]
    assert offenders == []


def test_sandbox_python_public_tool_signature_exposes_timeout_and_hides_services():
    signature = inspect.signature(tools_execution.sandbox_run_python)

    assert "timeout_ms" in signature.parameters
    assert signature.parameters["timeout_ms"].default is None
    assert list(signature.parameters).index("context") < list(signature.parameters).index("timeout_ms")
    assert "services" not in signature.parameters


def test_mcp_public_tool_hides_services_parameter():
    wrapped = _mcp_public_tool(datasource_create)

    signature = inspect.signature(wrapped)

    assert "services" not in signature.parameters
    assert "services" not in wrapped.__annotations__


def test_mcp_public_tool_resolves_forward_annotations():
    wrapped = _mcp_public_tool(analysis_upsert_table_profile)

    metadata_annotation = inspect.signature(wrapped).parameters["metadata"].annotation

    assert metadata_annotation != "JsonDict | None"


def test_all_registered_mcp_tools_hide_services_after_public_wrapping():
    for fn in PUBLIC_TOOL_FUNCTIONS + ANALYSIS_CONTEXT_PUBLIC_TOOL_FUNCTIONS:
        wrapped = _mcp_public_tool(fn)
        signature = inspect.signature(wrapped)
        assert "services" not in signature.parameters, fn.__name__
        assert "services" not in getattr(wrapped, "__annotations__", {}), fn.__name__


def test_analysis_context_public_tools_do_not_accept_internal_kwargs():
    offenders = [
        fn.__name__
        for fn in ANALYSIS_CONTEXT_PUBLIC_TOOL_FUNCTIONS
        if any(param.kind is inspect.Parameter.VAR_KEYWORD for param in inspect.signature(fn).parameters.values())
    ]
    assert offenders == []

    with pytest.raises(TypeError):
        tools_analysis_context.analysis_catalog_search("ds_1", "orders", services=object())


def test_analysis_context_tools_expose_impl_entrypoints():
    expected_impl_names = [
        "analysis_catalog_search_impl",
        "analysis_get_table_profile_impl",
        "analysis_get_column_profile_impl",
        "analysis_semantic_search_impl",
        "analysis_get_join_paths_impl",
        "analysis_build_context_impl",
        "analysis_profile_datasource_impl",
        "analysis_load_semantic_seed_impl",
        "analysis_upsert_table_profile_impl",
        "analysis_upsert_column_profile_impl",
        "analysis_upsert_metric_impl",
        "analysis_upsert_business_term_impl",
        "analysis_upsert_mart_impl",
        "analysis_upsert_join_path_impl",
    ]
    missing = [name for name in expected_impl_names if not hasattr(tools_analysis_context, name)]
    assert missing == []

    for name in expected_impl_names:
        signature = inspect.signature(getattr(tools_analysis_context, name))
        assert "services" in signature.parameters, name


def test_create_mcp_server_registers_tools_without_schema_error():
    server = create_mcp_server()

    assert server is not None
