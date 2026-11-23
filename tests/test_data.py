from datetime import date

import pytest

from rra.cache import FileCache, NullCache
from rra.data import DataError, MarketData, normalize_code, parse_reports

from conftest import SAMPLE_ROWS


def test_normalize_code():
    assert normalize_code("600519") == "600519"
    assert normalize_code("sh600519") == "600519"
    assert normalize_code("000001.SZ") == "000001"
    with pytest.raises(DataError):
        normalize_code("abc")


def test_parse_reports_fields_and_forecasts():
    reports = parse_reports(SAMPLE_ROWS)
    assert [r["date"] for r in reports] == sorted([r["date"] for r in reports], reverse=True)
    first = reports[0]
    assert first["report_id"] == "H3_A_1"
    assert first["org"] == "中邮证券"
    assert first["forecasts"] == {"2026": {"eps": 66.87, "pe": 20.0}, "2027": {"eps": 70.66, "pe": 18.0}}
    # NaN 的 EPS 年份被丢弃
    assert list(reports[-1]["forecasts"]) == ["2026"]


def test_list_reports_filters_by_days(fake_ak):
    md = MarketData(NullCache(), ak=fake_ak)
    got = md.list_reports("600519", days=60, today=date(2026, 11, 23))
    assert [r["report_id"] for r in got] == ["H3_A_1", "H3_B_1", "H3_C_1"]


def test_find_report_unknown(fake_ak):
    md = MarketData(NullCache(), ak=fake_ak)
    with pytest.raises(DataError):
        md.find_report("600519", "nope")


def test_cache_hits(tmp_path, fake_ak):
    md = MarketData(FileCache(tmp_path), ak=fake_ak)
    md.all_reports("600519")
    md.all_reports("600519")
    assert fake_ak.calls == 1


def test_stock_info_and_prices(fake_ak):
    md = MarketData(NullCache(), ak=fake_ak)
    assert md.stock_info("600519")["price"] == 1441.9
    prices = md.price_history("600519", date(2026, 11, 1), date(2026, 11, 22))
    assert prices[-1] == {"date": "2026-11-20", "close": 1485.75, "pct_chg": 1.75}


def test_fetch_error_wrapped():
    class Broken:
        def stock_research_report_em(self, symbol):
            raise ConnectionError("boom")

    md = MarketData(NullCache(), ak=Broken())
    with pytest.raises(DataError, match="boom"):
        md.all_reports("600519")


@pytest.mark.network
def test_real_reports(tmp_path):
    md = MarketData(FileCache(tmp_path))
    reports = md.list_reports("600519", days=365)
    assert reports and reports[0]["pdf_url"].startswith("http")


def test_price_fallback_to_tencent(fake_ak):
    import pandas as pd

    def broken(**kw):
        raise ConnectionError("限流")

    seen = {}

    def tx(symbol, start_date, end_date, adjust):
        seen["symbol"] = symbol
        return pd.DataFrame({"date": ["2026-11-19", "2026-11-20"], "close": [100.0, 110.0]})

    fake_ak.stock_zh_a_hist_em = broken
    fake_ak.stock_zh_a_hist_tx = tx
    prices = MarketData(NullCache(), ak=fake_ak).price_history("600519", date(2026, 11, 1), date(2026, 11, 22))
    assert seen["symbol"] == "sh600519"
    assert prices == [
        {"date": "2026-11-19", "close": 100.0, "pct_chg": None},
        {"date": "2026-11-20", "close": 110.0, "pct_chg": 10.0},
    ]


def test_exchange_prefix():
    from rra.data import exchange_prefix

    assert [exchange_prefix(c) for c in ("600519", "000001", "300750", "830799")] == ["sh", "sz", "sz", "bj"]
