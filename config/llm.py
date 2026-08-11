"""Model settings. API credentials are read only from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 900
    timeout_s: float = 20.0
    transport_retries: int = 2
    max_refines: int = 2

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            model=os.getenv("LLM_IMBM_MODEL", ""),
            base_url=os.getenv("LLM_IMBM_BASE_URL", "").rstrip("/"),
            api_key=os.getenv("LLM_IMBM_API_KEY", ""),
        )

    @property
    def configured(self) -> bool:
        return bool(self.model and self.base_url and self.api_key)
