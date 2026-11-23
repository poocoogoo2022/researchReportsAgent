"""工具调用循环。"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .llm import ChatResult, LLMClient
from .tools import TOOL_SCHEMAS, Toolkit

FINALIZE_PROMPT = "已达到工具调用步数上限。请不要再调用工具，基于已获得的信息直接给出最终回答。"


@dataclass
class StepLog:
    tool: str
    arguments: str
    seconds: float
    result_chars: int


@dataclass
class RunResult:
    answer: str
    steps: list[StepLog] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        toolkit: Toolkit,
        system_prompt: str,
        max_steps: int = 12,
        on_step: Callable[[StepLog], None] | None = None,
    ):
        self.llm = llm
        self.toolkit = toolkit
        self.system_prompt = system_prompt
        self.max_steps = max_steps
        self.on_step = on_step

    def run(self, task: str) -> RunResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        result = RunResult(answer="")

        for _ in range(self.max_steps):
            resp = self._chat(messages, TOOL_SCHEMAS, result)
            if not resp.tool_calls:
                result.answer = resp.content or ""
                return result
            messages.append(_assistant_message(resp))
            for call in resp.tool_calls:
                t0 = time.monotonic()
                output = self.toolkit.call(call.name, call.arguments)
                log = StepLog(call.name, call.arguments, time.monotonic() - t0, len(output))
                result.steps.append(log)
                if self.on_step:
                    self.on_step(log)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

        messages.append({"role": "user", "content": FINALIZE_PROMPT})
        resp = self._chat(messages, None, result)
        result.answer = resp.content or ""
        return result

    def _chat(self, messages, tools, result: RunResult) -> ChatResult:
        resp = self.llm.chat(messages, tools)
        for k, v in resp.usage.items():
            result.usage[k] = result.usage.get(k, 0) + v
        return resp


def _assistant_message(resp: ChatResult) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": resp.content or "",
        "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in resp.tool_calls
        ],
    }


def print_step(log: StepLog) -> None:
    args = log.arguments if len(log.arguments) < 120 else log.arguments[:117] + "..."
    print(f"  → {log.tool}({args})  {log.seconds:.1f}s  {log.result_chars} 字", file=sys.stderr)


__all__ = ["Agent", "RunResult", "StepLog", "print_step"]
