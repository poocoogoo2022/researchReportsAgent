"""LLM 客户端。Agent 只依赖 LLMClient 协议，测试可替换为脚本实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class LLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> ChatResult: ...


class OpenAICompatClient:
    """OpenAI 兼容 Chat Completions（默认 DeepSeek）。"""

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.3, timeout: float = 120):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2)
        self.model = model
        self.temperature = temperature

    def chat(self, messages, tools):
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            kwargs["tools"] = tools
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])]
        usage = {}
        if resp.usage:
            usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
        return ChatResult(msg.content, calls, usage)


class ScriptedLLM:
    """按预设顺序返回结果，并记录收到的消息。测试用。"""

    def __init__(self, script: list[ChatResult]):
        self.script = list(script)
        self.received: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools):
        self.received.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("ScriptedLLM 脚本已用完")
        return self.script.pop(0)
