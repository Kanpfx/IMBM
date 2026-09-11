"""OpenAI-compatible HTTP client using a worker thread while callers await results."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import request
from urllib.parse import urlparse

from config.llm import LLMConfig


class LLMClientError(RuntimeError):
    pass


def _is_official_deepseek_api(base_url: str) -> bool:
    return urlparse(base_url).hostname == "api.deepseek.com"


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.config.configured:
            raise LLMClientError("LLM_MODEL, LLM_BASE_URL and LLM_API_KEY are required")
        last_error: Exception | None = None
        for attempt in range(self.config.transport_retries + 1):
            try:
                return await asyncio.to_thread(
                    self._complete_sync, self.prepare_messages(messages)
                )
            except (OSError, TimeoutError, ValueError) as exc:
                last_error = exc
                if attempt < self.config.transport_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise LLMClientError(f"LLM request failed: {last_error}")

    @staticmethod
    def prepare_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Return the agent-authored messages without adding another system role."""
        return list(messages)

    def _complete_sync(self, messages: list[dict[str, str]]) -> str:
        url = self.config.base_url
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if _is_official_deepseek_api(self.config.base_url):
            body["thinking"] = {"type": "disabled"}
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.config.timeout_s) as response:
            result = json.loads(response.read().decode("utf-8"))
        return str(result["choices"][0]["message"]["content"]).strip()
