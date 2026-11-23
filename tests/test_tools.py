import json
from datetime import date

from rra.cache import NullCache
from rra.data import MarketData
from rra.pdf import ReportReader
from rra.tools import TOOL_SCHEMAS, Toolkit


def make_toolkit(fake_ak, max_reads=6):
    reader = ReportReader(NullCache(), downloader=lambda u: b"")
    reader.full_text = lambda url: f"正文 {url}"
    return Toolkit(MarketData(NullCache(), ak=fake_ak), reader, today=date(2026, 11, 23), max_reads=max_reads)


def test_schemas_match_methods(fake_ak):
    tk = make_toolkit(fake_ak)
    for s in TOOL_SCHEMAS:
        assert callable(getattr(tk, s["function"]["name"]))


def test_list_and_read(fake_ak):
    tk = make_toolkit(fake_ak)
    reports = json.loads(tk.call("list_reports", '{"code": "600519", "days": 30}'))
    assert [r["report_id"] for r in reports] == ["H3_A_1", "H3_B_1"]
    got = json.loads(tk.call("read_report", {"code": "600519", "report_id": "H3_A_1"}))
    assert got["text"].startswith("正文 https://pdf.dfcfw.com")


def test_read_limit(fake_ak):
    tk = make_toolkit(fake_ak, max_reads=1)
    tk.call("read_report", {"code": "600519", "report_id": "H3_A_1"})
    assert "上限" in tk.call("read_report", {"code": "600519", "report_id": "H3_B_1"})


def test_errors_returned_as_text(fake_ak):
    tk = make_toolkit(fake_ak)
    assert "未知工具" in tk.call("rm_rf", "{}")
    assert "参数错误" in tk.call("list_reports", "not json")
    assert "参数错误" in tk.call("list_reports", '{"symbol": "600519"}')
    assert "无效" in tk.call("get_stock_info", '{"code": "abc"}')
    assert "找不到" in tk.call("read_report", '{"code": "600519", "report_id": "zzz"}')


def test_performance_and_consensus(fake_ak):
    tk = make_toolkit(fake_ak)
    perf = json.loads(tk.call("get_post_report_performance", '{"code": "600519", "days": 30}'))
    assert perf[0]["report_id"] == "H3_A_1"
    assert perf[0]["ret_1d"] == round((1485.75 / 1460.21 - 1) * 100, 2)
    cons = json.loads(tk.call("get_eps_consensus", '{"code": "600519"}'))
    assert cons["2026"]["n"] == 2
