from __future__ import annotations

from data_agent_backend.models.common import BackendError
from data_agent_backend.models.contexts import PolicyContext


def test_workspace_write_overwrite_and_root_listing(services):
    ctx = PolicyContext(run_id="run1")
    first = services.workspace_backend.write_text("/workspace/note.txt", "hello", ctx)
    second = services.workspace_backend.write_text("/workspace/note.txt", "world", ctx)
    assert first.overwritten is False
    assert second.overwritten is True
    assert services.workspace_backend.read_text("/workspace/note.txt", ctx) == "world"
    root = {entry.path for entry in services.workspace_backend.list("/", ctx)}
    assert "/secrets" not in root
    assert {"/workspace", "/artifacts", "/catalog", "/memory", "/skills", "/exports"} <= root


def test_workspace_blocks_artifacts_catalog_traversal_and_secrets(services):
    ctx = PolicyContext(run_id="run1")
    for path in ["/artifacts/foo.csv", "/catalog/schema.md"]:
        try:
            services.workspace_backend.write_text(path, "x", ctx)
        except BackendError as exc:
            assert exc.code == "POLICY_BLOCKED"
        else:
            raise AssertionError("write should be blocked")

    for path in ["/workspace/../secrets/x", "C:/Users/User/secret.txt", "/secrets/api_key"]:
        try:
            services.workspace_backend.read_text(path, ctx)
        except BackendError as exc:
            assert exc.code == "POLICY_BLOCKED"
        else:
            raise AssertionError("path should be blocked")


def test_workspace_delegates_to_router_mount(services):
    ctx = PolicyContext(run_id="run1")
    services.workspace_backend.write_text("/workspace/a/b.txt", "content", ctx)
    entries = services.workspace_backend.list("/workspace/a", ctx)
    assert entries[0].path == "/workspace/a/b.txt"

