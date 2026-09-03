"""Common agent shape for the LLM-controlled runtime."""

from __future__ import annotations

from config.llm import LLMConfig
from llm.client import LLMClient


class BaseAgent:
    def __init__(self, config: LLMConfig, llm_client: LLMClient):
        self.model_name = config.model
        self.generation_config = config
        self.llm_client = llm_client
