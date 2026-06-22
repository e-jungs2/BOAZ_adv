from __future__ import annotations

import pytest

from data_agent_backend.config import BackendConfig
from data_agent_backend.services import create_backend_services


@pytest.fixture()
def services(tmp_path):
    config = BackendConfig(base_data_dir=tmp_path / ".data_agent")
    return create_backend_services(config)

