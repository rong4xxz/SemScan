"""
LLM client: ChatMessage, TokenUsage, and LLMClient.
Uses an OpenAI-compatible interface and can work with DeepSeek / SiliconFlow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional

from openai import AsyncOpenAI


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class TokenUsage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, usage: object) -> None:
        if usage is None:
            return
        self.requests += 1
        self.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        self.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
        self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)

    def to_dict(self) -> dict:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class LLMClient:
    """
    OpenAI-compatible Chat Completions client.
    Uses the openai>=1.x SDK and can work with DeepSeek / SiliconFlow-compatible APIs.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_s: float = 180.0,
    ):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
        self._model = model
        self.usage = TokenUsage()

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        *,
        messages: List[ChatMessage],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_headers=extra_headers,
        )
        try:
            self.usage.add(getattr(resp, "usage", None))
        except Exception:
            pass
        return (resp.choices[0].message.content or "").strip()
