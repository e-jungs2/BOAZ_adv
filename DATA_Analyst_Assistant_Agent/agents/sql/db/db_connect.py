"""[호환 심] 실제 구현은 `DATA_Analyst_Assistant_Agent.shared.db` 로 이동했다."""

from DATA_Analyst_Assistant_Agent.shared.db import (  # noqa: F401
    get_db_engine,
    get_table_samples,
)
