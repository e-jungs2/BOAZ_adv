from __future__ import annotations

from data_agent_backend.models.common import BackendError
from data_agent_backend.models.tool_results import ToolResult


def test_tool_result_success_shape_is_stable():
    result = ToolResult.success({"status": "ok"}).model_dump(mode="json")

    assert result == {"ok": True, "data": {"status": "ok"}, "error": None}


def test_tool_result_failure_shape_is_stable():
    result = ToolResult.failure(
        "EXAMPLE_ERROR",
        "Example failed.",
        {"suggestion": "Retry with a smaller request.", "retryable": True},
    ).model_dump(mode="json")

    assert result == {
        "ok": False,
        "data": None,
        "error": {
            "code": "EXAMPLE_ERROR",
            "message": "Example failed.",
            "details": {"suggestion": "Retry with a smaller request.", "retryable": True},
        },
    }


def test_tool_result_from_backend_error_preserves_details():
    exc = BackendError(
        "DATASOURCE_QUERY_ERROR",
        "Datasource query failed.",
        {"suggestion": "Inspect catalog.", "retryable": False, "query_artifact_id": "art_query"},
    )

    result = ToolResult.from_exception(exc).model_dump(mode="json")

    assert result["ok"] is False
    assert result["error"]["code"] == "DATASOURCE_QUERY_ERROR"
    assert result["error"]["message"] == "Datasource query failed."
    assert result["error"]["details"] == {
        "suggestion": "Inspect catalog.",
        "retryable": False,
        "query_artifact_id": "art_query",
    }


def test_tool_result_from_unknown_exception_masks_message():
    result = ToolResult.from_exception(ValueError("secret internal value")).model_dump(mode="json")

    assert result["ok"] is False
    assert result["data"] is None
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert result["error"]["message"] == "An internal backend error occurred."
    assert result["error"]["details"] == {"type": "ValueError"}
