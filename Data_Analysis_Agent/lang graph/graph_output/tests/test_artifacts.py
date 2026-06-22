from __future__ import annotations

from data_agent_backend.models.artifacts import ArtifactRegisterRequest, ArtifactType
from data_agent_backend.models.contexts import PolicyContext


def test_artifact_registration_store_registry_preview_and_lineage(services):
    ctx = PolicyContext(run_id="run1")
    parent = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(run_id="run1", type=ArtifactType.sql_query, content_text="select 1", created_by_tool="test"),
        ctx,
    )
    child = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(
            run_id="run1",
            type=ArtifactType.sql_result,
            content_text="x\n1\n",
            filename="result.csv",
            created_by_tool="test",
            parent_ids=[parent.artifact_id],
            lineage_edge_type="query_result_of",
        ),
        ctx,
    )
    assert parent.artifact_id != child.artifact_id
    assert services.artifact_store.exists(child.artifact_id)
    assert child.preview["columns"] == ["x"]
    lineage = services.artifact_registry.get_lineage(child.artifact_id)
    assert lineage[0]["edge_type"] == "query_result_of"
    stored_metadata = services.sqlite.query_one("SELECT metadata_json FROM artifacts WHERE artifact_id = ?", (child.artifact_id,))
    assert "1\\n" not in stored_metadata["metadata_json"]


def test_preview_failure_does_not_fail_registration(services, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("preview broke")

    monkeypatch.setattr(services.artifact_registry, "_generate_preview", boom)
    record = services.artifact_registry.register_artifact(
        ArtifactRegisterRequest(run_id="run1", type=ArtifactType.report, content_text="hello", created_by_tool="test"),
        PolicyContext(run_id="run1"),
    )
    assert record.metadata["preview_error"].startswith("RuntimeError")

