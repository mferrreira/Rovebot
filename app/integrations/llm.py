from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 20.0):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        response = httpx.post(
            self.base_url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage", {})
        logger.info("LLM — in=%s out=%s tokens", usage.get("input_tokens"), usage.get("output_tokens"))
        return "\n".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
