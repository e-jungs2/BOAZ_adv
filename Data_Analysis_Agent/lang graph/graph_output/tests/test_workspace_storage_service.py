from __future__ import annotations

import json

from data_agent_backend.models.artifacts import ArtifactRef, ArtifactType
from data_agent_backend.models.common import BackendError
from data_agent_backend.services.workspace_storage_service import WorkspaceStorageService


def test_workspace_storage_is_available_from_factory(services):
    assert isinstance(services.workspace_storage, WorkspaceStorageService)


def test_save_sql_query_returns_ref_and_default_filename(services):
    ref = services.workspace_storage.save_sql_query("run1", "select 1 as x")

    assert isinstance(ref, ArtifactRef)
    assert ref.type == ArtifactType.sql_query
    record = services.workspace_storage.get_artifact(ref.artifact_id)
    assert record.local_path.endswith("query.sql")
    assert record.metadata["format"] == "sql"


def test_save_json_sql_result_builds_preview(services):
    ref = services.workspace_storage.save_sql_result("run1", [{"x": 1, "y": "a"}, {"x": 2, "z": "b"}])

    record = services.workspace_storage.get_artifact(ref.artifact_id)
    assert record.local_path.endswith("result.json")
    assert record.preview == {
        "row_count": 2,
        "columns": ["x", "y", "z"],
        "sample_rows": [{"x": 1, "y": "a"}, {"x": 2, "z": "b"}],
    }
    assert json.loads(services.artifact_store.read_text(ref.artifact_id)) == [{"x": 1, "y": "a"}, {"x": 2, "z": "b"}]


def test_save_execution_log_filters_to_standard_fields(services):
    ref = services.workspace_storage.save_execution_log(
        "run1",
        {
            "status": "success",
            "stdout": "hello",
            "stderr": "",
            "exit_code": 0,
            "runtime_ms": 12,
            "artifacts": ["art1"],
            "provider_secret": "drop-me",
        },
    )

    stored = json.loads(services.artifact_store.read_text(ref.artifact_id))
    assert "provider_secret" not in stored
    assert stored["status"] == "success"
    record = services.workspace_storage.get_artifact(ref.artifact_id)
    assert record.metadata["status"] == "success"
    assert record.metadata["exit_code"] == 0
    assert record.preview["stdout_snippet"] == "hello"


def test_save_chart_requires_allowed_base_dir(services, tmp_path):
    allowed = tmp_path / "sandbox-out"
    allowed.mkdir()
    chart = allowed / "plot.png"
    chart.write_bytes(b"png-data")

    ref = services.workspace_storage.save_chart("run1", chart, allowed_base_dir=allowed)
    record = services.workspace_storage.get_artifact(ref.artifact_id)
    assert ref.type == ArtifactType.chart
    assert record.local_path.endswith("chart.png")
    assert services.artifact_store.read_bytes(ref.artifact_id) == b"png-data"

    outside = tmp_path / "plot.png"
    outside.write_bytes(b"nope")
    try:
        services.workspace_storage.save_chart("run1", outside, allowed_base_dir=allowed)
    except BackendError as exc:
        assert exc.code == "POLICY_BLOCKED"
    else:
        raise AssertionError("outside chart path should be blocked")


def test_save_report_preview_and_list_run_artifacts(services):
    services.workspace_storage.save_report("run-other", "# Other\n\nIgnore")
    ref = services.workspace_storage.save_report("run1", "# Report\n\nBody")

    record = services.workspace_storage.get_artifact(ref.artifact_id)
    assert record.local_path.endswith("report.md")
    assert record.preview["title"] == "# Report"
    run_artifacts = services.workspace_storage.list_run_artifacts("run1")
    assert [artifact.artifact_id for artifact in run_artifacts] == [ref.artifact_id]
    assert services.workspace_storage.preview_artifact(ref.artifact_id)["snippet"].startswith("# Report")
