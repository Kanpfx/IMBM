"""Model settings. API credentials are read only from the environment."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LLMConfig:
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int = 900
    timeout_s: float = 20.0
    transport_retries: int = 2
    max_refines: int = 3

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

