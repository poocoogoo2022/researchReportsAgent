from __future__ import annotations

import pandas as pd
import pytest


def report_row(date, org, rating, eps26, eps27=None, title="点评", pdf="H3_AP1"):
    return {
        "序号": 1, "股票代码": "600519", "股票简称": "贵州茅台", "报告名称": title,
        "东财评级": rating, "机构": org, "近一月个股研报数": 3,
        "2026-盈利预测-收益": eps26, "2026-盈利预测-市盈率": 20.0,
        "2027-盈利预测-收益": eps27, "2027-盈利预测-市盈率": 18.0,
        "行业": "白酒Ⅱ", "日期": date,
        "报告PDF链接": f"https://pdf.dfcfw.com/pdf/{pdf}_1.pdf?1.pdf",
    }


SAMPLE_ROWS = [
    report_row("2026-11-19", "中邮证券", "买入", 66.87, 70.66, "利润略超预期", "H3_A"),
    report_row("2026-11-13", "太平洋", "增持", 67.03, 69.45, "三季度业绩转正", "H3_B"),
    report_row("2026-10-10", "中邮证券", "增持", 65.00, 68.00, "中报点评", "H3_C"),
    report_row("2026-06-01", "西南证券", "买入", 70.00, float("nan"), "深度报告", "H3_D"),
]


class FakeAk:
    def __init__(self, rows=SAMPLE_ROWS):
        self.rows = rows
        self.calls = 0

    def stock_research_report_em(self, symbol):
        self.calls += 1
        return pd.DataFrame(self.rows)

    def stock_individual_info_em(self, symbol):
        return pd.DataFrame({"item": ["最新", "股票简称", "总市值", "行业"], "value": [1441.9, "贵州茅台", 1.8e12, "白酒Ⅱ"]})

    def stock_zh_a_hist_em(self, symbol, period, start_date, end_date, adjust):
        return pd.DataFrame({"日期": ["2026-11-19", "2026-11-20"], "收盘": [1460.21, 1485.75], "涨跌幅": [1.22, 1.75]})


@pytest.fixture
def fake_ak():
    return FakeAk()
