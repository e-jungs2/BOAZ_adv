"""[호환 심] 실제 구현은 `DATA_Analyst_Assistant_Agent.shared.llm` 로 이동했다.

기존 `from DATA_Analyst_Assistant_Agent.llm import get_chat_model` 등을 깨지 않기 위한 re-export.
신규 코드는 `shared.llm` 을 직접 import 할 것.
"""

from DATA_Analyst_Assistant_Agent.shared.llm import (  # noqa: F401
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_BASE_URL,
    get_chat_model,
    get_model_name,
)
