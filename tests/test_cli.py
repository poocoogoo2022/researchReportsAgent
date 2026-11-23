import json
from datetime import date

import openai
import pytest

# OpenAI SDK 3 uses httpx2, while SDK 1 and 2 use httpx.
if int(openai.__version__.split(".")[0]) >= 3:
    import httpx2 as httpx
else:
    import httpx

from rra import cli
from rra.cache import NullCache
from rra.data import MarketData


def test_reports_command(fake_ak, capsys, monkeypatch):
    market = MarketData(NullCache(), ak=fake_ak)
    monkeypatch.setattr(market, "list_reports", lambda code, days: market.all_reports(code))
    cli.cmd_reports(market, "600519", 365)
    out = capsys.readouterr().out
    assert "贵州茅台(600519)" in out
    assert "中邮证券 上调：增持 → 买入" in out
    assert "2026: 均值" in out


@pytest.mark.parametrize("dotenv", [None, "RRA_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx\n"])
def test_digest_requires_real_api_key(monkeypatch, tmp_path, capsys, dotenv):
    monkeypatch.delenv("RRA_API_KEY", raising=False)
    monkeypatch.setenv("RRA_CACHE_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv, encoding="utf-8")
    assert cli.main(["digest", "600519"]) == 2
    assert "RRA_API_KEY" in capsys.readouterr().err
    # load_dotenv writes to os.environ; remove the value it loaded in this test.
    monkeypatch.delenv("RRA_API_KEY", raising=False)


@pytest.fixture
def model_transport(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RRA_API_KEY", "test-key")
    monkeypatch.setenv("RRA_BASE_URL", "https://model.example.test")
    monkeypatch.setenv("RRA_MODEL", "test-model")
    monkeypatch.setenv("RRA_CACHE_DIR", str(tmp_path / "cache"))
    actual_openai = openai.OpenAI

    def install(handler):
        http = httpx.Client(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: actual_openai(http_client=http, **kwargs))
        return http

    return install


def completion(message):
    return httpx.Response(200, json={
        "id": "test-response", "object": "chat.completion", "created": 1, "model": "test-model",
        "choices": [{"index": 0, "message": message,
                     "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
    })


@pytest.mark.parametrize("command", ["digest", "ask"])
def test_agent_commands_with_mock_model_http(command, model_transport, fake_ak, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "MarketData", lambda cache: MarketData(cache, ak=fake_ak))

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 23)

    monkeypatch.setattr(cli, "date", FixedDate)
    requests = []
    question = "最近机构怎样看盈利？"
    answer = "# 模拟解读\n中邮证券（2026-11-19）发布研报。"

    def handler(request):
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "test-model"
        assert any(t["function"]["name"] == "list_reports" for t in body["tools"])
        if len(requests) == 1:
            assert (question if command == "ask" else "生成一份研报解读") in body["messages"][-1]["content"]
            return completion({"role": "assistant", "tool_calls": [{
                "id": "call_1", "type": "function", "function": {
                    "name": "list_reports", "arguments": '{"code":"600519","days":30}',
                },
            }]})
        message = body["messages"][-1]
        assert message["role"] == "tool" and message["tool_call_id"] == "call_1"
        assert [r["org"] for r in json.loads(message["content"])] == ["中邮证券", "太平洋"]
        return completion({"role": "assistant", "content": answer})

    output = tmp_path / "reports" / "out.md"
    args = ["-o", str(output)] if command == "digest" else [question, "-q"]
    with model_transport(handler):
        assert cli.main([command, "600519", "--days", "30", *args]) == 0
    captured = capsys.readouterr()
    assert len(requests) == 2
    assert captured.out == answer + "\n"
    if command == "digest":
        assert output.read_text(encoding="utf-8") == captured.out
    else:
        assert not captured.err


@pytest.mark.parametrize("status, expected", [(401, "鉴权失败"), (402, "HTTP 402"), (200, "未返回正文")])
def test_digest_does_not_write_output_on_model_failure(status, expected, model_transport, tmp_path, capsys):
    def handler(request):
        if status == 200:
            return completion({"role": "assistant", "content": " "})
        return httpx.Response(status, json={"error": {"message": "provider error details"}})

    output = tmp_path / "out.md"
    output.write_text("旧报告", encoding="utf-8")
    with model_transport(handler):
        assert cli.main(["digest", "600519", "-o", str(output)]) == 1
    captured = capsys.readouterr()
    assert expected in captured.err
    assert "provider error details" not in captured.err
    assert not captured.out
    assert output.read_text(encoding="utf-8") == "旧报告"
