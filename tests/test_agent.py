import json
from datetime import date

from rra.agent import Agent
from rra.cache import NullCache
from rra.data import MarketData
from rra.llm import ChatResult, ScriptedLLM, ToolCall
from rra.pdf import ReportReader
from rra.tools import Toolkit


def make_toolkit(fake_ak):
    reader = ReportReader(NullCache())
    reader.full_text = lambda url: "投资要点：直销占比提升"
    return Toolkit(MarketData(NullCache(), ak=fake_ak), reader, today=date(2026, 11, 23))


def test_agent_runs_tools_then_answers(fake_ak):
    llm = ScriptedLLM([
        ChatResult(None, [ToolCall("c1", "list_reports", '{"code": "600519", "days": 30}')], {"prompt_tokens": 10}),
        ChatResult(None, [ToolCall("c2", "read_report", '{"code": "600519", "report_id": "H3_A_1"}'),
                          ToolCall("c3", "get_eps_consensus", '{"code": "600519", "days": 30}')], {"prompt_tokens": 20}),
        ChatResult("# 解读\n直销占比提升", [], {"prompt_tokens": 30, "completion_tokens": 5}),
    ])
    result = Agent(llm, make_toolkit(fake_ak), "sys").run("task")

    assert result.answer.startswith("# 解读")
    assert [s.tool for s in result.steps] == ["list_reports", "read_report", "get_eps_consensus"]
    assert result.usage == {"prompt_tokens": 60, "completion_tokens": 5}

    last = llm.received[-1]
    assert [m["role"] for m in last] == ["system", "user", "assistant", "tool", "assistant", "tool", "tool"]
    tool_msgs = {m["tool_call_id"]: m["content"] for m in last if m["role"] == "tool"}
    assert "直销占比提升" in json.loads(tool_msgs["c2"])["text"]
    assert json.loads(tool_msgs["c3"])["2026"]["n"] == 2


def test_agent_tool_error_is_fed_back(fake_ak):
    llm = ScriptedLLM([
        ChatResult(None, [ToolCall("c1", "read_report", '{"code": "600519", "report_id": "bad"}')]),
        ChatResult("没找到", []),
    ])
    result = Agent(llm, make_toolkit(fake_ak), "sys").run("task")
    assert result.answer == "没找到"
    assert "找不到研报" in llm.received[-1][-1]["content"]


def test_agent_step_limit_forces_final_answer(fake_ak):
    loop = ChatResult(None, [ToolCall("c", "get_stock_info", '{"code": "600519"}')])
    llm = ScriptedLLM([loop, loop, ChatResult("最终回答", [])])
    result = Agent(llm, make_toolkit(fake_ak), "sys", max_steps=2).run("task")
    assert result.answer == "最终回答"
    assert len(result.steps) == 2
    assert "步数上限" in llm.received[-1][-1]["content"]
