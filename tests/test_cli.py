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
from rra.data import DataError, MarketData
from rra.pdf import ReportReader


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


@pytest.fixture
def digest_data(fake_ak, monkeypatch):
    market = MarketData(NullCache(), ak=fake_ak)
    monkeypatch.setattr(cli, "MarketData", lambda cache: market)
    monkeypatch.setattr(ReportReader, "full_text", lambda self, url: "研报正文节选：直销增长。")

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 23)

    monkeypatch.setattr(cli, "date", FixedDate)
    return market


def test_ask_still_executes_model_tools(model_transport, digest_data, capsys):
    calls = []
    question = "最近机构怎样看盈利？"
    answer = "# 模拟解读\n中邮证券（2026-11-19）发布研报。"

    def handler(request):
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        calls.append(body)
        assert body["model"] == "test-model"
        assert any(t["function"]["name"] == "list_reports" for t in body["tools"])
        if len(calls) == 1:
            assert question in body["messages"][-1]["content"]
            return completion({"role": "assistant", "tool_calls": [{
                "id": "call_1", "type": "function", "function": {
                    "name": "list_reports", "arguments": '{"code":"600519","days":30}',
                },
            }]})
        message = body["messages"][-1]
        assert message["role"] == "tool" and message["tool_call_id"] == "call_1"
        assert [r["org"] for r in json.loads(message["content"])] == ["中邮证券", "太平洋"]
        return completion({"role": "assistant", "content": answer})

    with model_transport(handler):
        assert cli.main(["ask", "600519", question, "--days", "30", "-q"]) == 0
    captured = capsys.readouterr()
    assert len(calls) == 2
    assert captured.out == answer + "\n"
    assert not captured.err


def test_digest_renders_its_own_tables_and_resolves_citations(model_transport, digest_data, tmp_path, capsys):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "tools" not in body
        [excerpt] = json.loads(body["messages"][-1]["content"])
        assert excerpt["report_id"] == "H3_A_1"
        assert "forecasts" not in excerpt and "pdf_url" not in excerpt
        source = {"report_id": "H3_A_1", "quote": "研报正文节选：直销增长。", "period": None}
        findings = {"themes": [
            {"text": "直销增长。", "sources": [source]},
            {"text": "未读报告的结论", "sources": [{**source, "report_id": "H3_B_1"}]},
            {"text": "杜撰链接：https://example.test", "sources": [source]},
            {"text": "无引用的结论", "sources": []},
        ], "differences": [], "risks": []}
        return completion({"role": "assistant", "content": json.dumps(findings)})

    output = tmp_path / "reports" / "out.md"
    with model_transport(handler):
        assert cli.main(["digest", "600519", "--days", "30", "--max-reads", "1", "-o", str(output)]) == 0
    assert len(calls) == 1
    out = capsys.readouterr().out
    assert output.read_text(encoding="utf-8") == out
    assert "区间内有 2 家机构发布 2 份研报" in out
    assert "| 买入 | 1 |" in out and "| 增持 | 1 |" in out
    assert "| 2026 | 2 | 66.95 |" in out
    assert "| 中邮证券 | 2026-11-19 | 1.75 | 缺数据 | 缺数据 |" in out
    assert "- 直销增长。" in out
    assert "[中邮证券（2026-11-19）](https://pdf.dfcfw.com/pdf/H3_A_1.pdf?1.pdf)（报告期：未识别）：「研报正文节选：直销增长。」" in out
    assert "未读报告的结论" not in out and "无引用的结论" not in out and "example.test" not in out


def test_digest_stats_only_without_key_or_prices(digest_data, monkeypatch, capsys):
    monkeypatch.delenv("RRA_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)

    def no_prices(*args):
        raise DataError("行情限流")

    def unexpected_call(*args, **kwargs):
        pytest.fail("纯统计不应读取 PDF 或构建模型客户端")

    monkeypatch.setattr(digest_data, "price_history", no_prices)
    monkeypatch.setattr(ReportReader, "full_text", unexpected_call)
    monkeypatch.setattr(openai, "OpenAI", unexpected_call)
    assert cli.main(["digest", "600519", "--days", "30", "--max-reads", "0"]) == 0
    out = capsys.readouterr().out
    assert "66.95" in out and "日线行情暂不可用" in out
    assert "本次只生成统计，未读取研报正文" in out


def test_digest_no_pdf_does_not_call_model(digest_data, model_transport, monkeypatch, capsys):
    attempts = []

    def no_pdf(self, url):
        attempts.append(url)
        raise DataError("扫描件")

    def unexpected_call(request):
        pytest.fail("没有可用正文时不应调用模型")

    monkeypatch.setattr(ReportReader, "full_text", no_pdf)
    with model_transport(unexpected_call):
        assert cli.main(["digest", "600519", "--days", "30", "--max-reads", "1"]) == 0
    assert len(attempts) == 1
    assert "未能读取可用的研报正文" in capsys.readouterr().out


def test_digest_empty_window_does_not_fetch_prices_or_call_model(digest_data, model_transport, monkeypatch, capsys):
    def unexpected_call(*args, **kwargs):
        pytest.fail("区间无研报时不应查行情、读 PDF 或调用模型")

    monkeypatch.setattr(digest_data, "price_history", unexpected_call)
    monkeypatch.setattr(ReportReader, "full_text", unexpected_call)
    with model_transport(unexpected_call):
        assert cli.main(["digest", "600519", "--days", "1"]) == 0
    assert "区间内没有可用研报" in capsys.readouterr().out


@pytest.mark.parametrize("flag, value", [("--days", "0"), ("--days", "731"), ("--max-reads", "-1"), ("--max-reads", "21")])
def test_digest_rejects_out_of_range_arguments(flag, value, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["digest", "600519", flag, value])
    assert exc.value.code == 2
    assert flag in capsys.readouterr().err


@pytest.mark.parametrize("status, expected", [(401, "鉴权失败"), (402, "HTTP 402"), (200, "未返回正文"), (201, "正文结构不符合要求")])
def test_digest_does_not_write_output_on_model_failure(status, expected, model_transport, digest_data, tmp_path, capsys):
    def handler(request):
        if status == 200:
            return completion({"role": "assistant", "content": " "})
        if status == 201:
            return completion({"role": "assistant", "content": '{"themes": [], "statistics": "伪造表格"}'})
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
