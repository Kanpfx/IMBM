"""IMBM-compatible common agent shape."""

from __future__ import annotations

from config.llm import LLMConfig
from tools.llm_client import LLMClient


class BaseAgent:
    def __init__(self, config: LLMConfig, llm_client: LLMClient):
        self.model_name = config.model
        self.generation_config = config
        self.llm_client = llm_client

