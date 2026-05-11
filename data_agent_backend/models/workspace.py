from __future__ import annotations

from enum import StrEnum

from .common import BackendModel, JsonDict


class WorkspaceEntryType(StrEnum):
    file = "file"
    directory = "directory"
    artifact = "artifact"
    memory = "memory"
    mount = "mount"


class WorkspaceEntry(BackendModel):
    path: str
    name: str
    type: WorkspaceEntryType
    size: int | None = None
    modified_at: str | None = None
    metadata: JsonDict = {}


class WorkspaceWriteResult(BackendModel):
    path: str
    bytes_written: int
    overwritten: bool = False


class WorkspacePreview(BackendModel):
    path: str
    kind: str
    preview: JsonDict

