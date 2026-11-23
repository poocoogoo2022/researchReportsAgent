from rra.analysis import eps_consensus, post_report_performance, rating_summary
from rra.data import parse_reports

from conftest import SAMPLE_ROWS

REPORTS = parse_reports(SAMPLE_ROWS)


def test_rating_summary():
    s = rating_summary(REPORTS)
    assert s["report_count"] == 4
    assert s["org_count"] == 3
    assert s["distribution"] == {"买入": 2, "增持": 1}
    by_org = {c["org"]: c for c in s["changes"]}
    assert by_org["中邮证券"]["action"] == "上调"
    assert by_org["中邮证券"]["prev_rating"] == "增持"
    assert by_org["太平洋"]["action"] == "首次覆盖(区间内)"
    assert s["changes"][0]["org"] == "中邮证券"


def test_eps_consensus_uses_latest_per_org():
    c = eps_consensus(REPORTS)
    y26 = c["2026"]
    assert y26["n"] == 3  # 中邮只取最新一份
    assert y26["max"] == {"org": "西南证券", "eps": 70.0}
    assert y26["min"] == {"org": "中邮证券", "eps": 66.87}
    assert y26["mean"] == round((66.87 + 67.03 + 70.0) / 3, 3)
    assert c["2027"]["n"] == 2  # 西南证券 2027 为 NaN


def test_post_report_performance():
    prices = [
        {"date": "2026-11-12", "close": 100.0},
        {"date": "2026-11-13", "close": 102.0},
        {"date": "2026-11-14", "close": 101.0},  # 研报发布日 11-15 为周末
        {"date": "2026-11-17", "close": 110.0},
    ]
    reports = [{"report_id": "x", "date": "2026-11-15", "org": "A", "rating": "买入"}]
    row = post_report_performance(reports, prices, horizons=(1, 5))[0]
    assert row["ret_1d"] == round((110 / 101 - 1) * 100, 2)
    assert row["ret_5d"] is None


def test_post_report_performance_before_history():
    prices = [{"date": "2026-11-20", "close": 1.0}, {"date": "2026-11-21", "close": 2.0}]
    reports = [{"report_id": "x", "date": "2026-01-01", "org": "A", "rating": None}]
    assert post_report_performance(reports, prices, horizons=(1,))[0]["ret_1d"] is None
