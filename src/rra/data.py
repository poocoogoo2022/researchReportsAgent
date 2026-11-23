"""akshare 封装。所有 akshare 列名访问集中在此文件。"""

from __future__ import annotations

import math
import re
import time
from datetime import date, timedelta
from typing import Any, Callable

from .cache import FileCache

REPORTS_TTL = 6 * 3600
PRICES_TTL = 3600
INFO_TTL = 3600

_FORECAST_COL = re.compile(r"^(\d{4})-盈利预测-(收益|市盈率)$")


class DataError(RuntimeError):
    """数据获取失败。"""


def normalize_code(code: str) -> str:
    m = re.fullmatch(r"(?:sh|sz|bj)?\.?(\d{6})(?:\.(?:SH|SZ|BJ))?", code.strip(), re.IGNORECASE)
    if not m:
        raise DataError(f"无效的 A 股代码：{code!r}，应为 6 位数字，如 600519")
    return m.group(1)


def exchange_prefix(code: str) -> str:
    """6/9 开头为上交所，4/8 开头为北交所，其余为深交所。"""
    if code[0] in "69":
        return "sh"
    if code[0] in "48":
        return "bj"
    return "sz"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _report_id(pdf_url: str, fallback: str) -> str:
    m = re.search(r"/([^/]+?)\.pdf", pdf_url or "")
    return m.group(1) if m else fallback


def _retry(fn: Callable[[], Any], what: str, attempts: int = 2) -> Any:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # akshare 抛出的异常类型不统一
            last = e
            if i + 1 < attempts:
                time.sleep(1)
    raise DataError(f"{what} 失败：{last}") from last


def parse_reports(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 stock_research_report_em 的行转为规整的 dict，按日期倒序。"""
    out = []
    for i, row in enumerate(records):
        forecasts: dict[str, dict[str, float | None]] = {}
        for col, val in row.items():
            m = _FORECAST_COL.match(str(col))
            if m:
                year, kind = m.groups()
                forecasts.setdefault(year, {})["eps" if kind == "收益" else "pe"] = _num(val)
        forecasts = {y: f for y, f in sorted(forecasts.items()) if f.get("eps") is not None}
        pdf_url = str(row.get("报告PDF链接") or "")
        out.append({
            "report_id": _report_id(pdf_url, f"row{i}"),
            "code": str(row.get("股票代码", "")),
            "name": str(row.get("股票简称", "")),
            "title": str(row.get("报告名称", "")),
            "rating": str(row.get("东财评级") or "").strip() or None,
            "org": str(row.get("机构", "")),
            "date": str(row.get("日期", ""))[:10],
            "industry": str(row.get("行业", "")),
            "pdf_url": pdf_url,
            "forecasts": forecasts,
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


class MarketData:
    """数据访问入口。fetchers 可注入，便于测试。"""

    def __init__(self, cache: FileCache, ak: Any = None):
        self.cache = cache
        self._ak = ak

    @property
    def ak(self) -> Any:
        if self._ak is None:
            import akshare  # 导入较慢，延迟加载

            self._ak = akshare
        return self._ak

    def all_reports(self, code: str) -> list[dict[str, Any]]:
        code = normalize_code(code)

        def fetch() -> list[dict[str, Any]]:
            df = _retry(lambda: self.ak.stock_research_report_em(symbol=code), f"获取 {code} 研报列表")
            return parse_reports(df.to_dict("records"))

        return self.cache.get_json("reports", code, REPORTS_TTL, fetch)

    def list_reports(self, code: str, days: int = 90, today: date | None = None) -> list[dict[str, Any]]:
        today = today or date.today()
        since = (today - timedelta(days=days)).isoformat()
        until = today.isoformat()
        return [r for r in self.all_reports(code) if since <= r["date"] <= until]

    def price_history_for_reports(self, code: str, reports: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
        if not reports:
            return []
        start = date.fromisoformat(min(r["date"] for r in reports)) - timedelta(days=10)
        return self.price_history(code, start, today)

    def find_report(self, code: str, report_id: str) -> dict[str, Any]:
        for r in self.all_reports(code):
            if r["report_id"] == report_id:
                return r
        raise DataError(f"找不到研报 {report_id}，请先用 list_reports 获取有效的 report_id")

    def stock_info(self, code: str) -> dict[str, Any]:
        code = normalize_code(code)

        def fetch() -> dict[str, Any]:
            df = _retry(lambda: self.ak.stock_individual_info_em(symbol=code), f"获取 {code} 基本信息")
            info = {str(r["item"]): r["value"] for r in df.to_dict("records")}
            return {
                "code": code,
                "name": str(info.get("股票简称", "")),
                "price": _num(info.get("最新")),
                "market_cap": _num(info.get("总市值")),
                "float_market_cap": _num(info.get("流通市值")),
                "industry": str(info.get("行业", "")),
                "list_date": str(info.get("上市时间", "")),
            }

        return self.cache.get_json("info", code, INFO_TTL, fetch)

    def price_history(self, code: str, start: date, end: date | None = None) -> list[dict[str, Any]]:
        code = normalize_code(code)
        end = end or date.today()
        s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

        def from_em() -> list[dict[str, Any]]:
            df = self.ak.stock_zh_a_hist_em(symbol=code, period="daily", start_date=s, end_date=e, adjust="qfq")
            return [
                {"date": str(r["日期"])[:10], "close": _num(r["收盘"]), "pct_chg": _num(r["涨跌幅"])}
                for r in df.to_dict("records")
            ]

        def from_tx() -> list[dict[str, Any]]:
            df = self.ak.stock_zh_a_hist_tx(symbol=exchange_prefix(code) + code, start_date=s, end_date=e, adjust="qfq")
            rows, prev = [], None
            for r in df.to_dict("records"):
                close = _num(r["close"])
                pct = round((close / prev - 1) * 100, 2) if close is not None and prev else None
                rows.append({"date": str(r["date"])[:10], "close": close, "pct_chg": pct})
                prev = close
            return rows

        def fetch() -> list[dict[str, Any]]:
            # 东财行情容易限流，失败后改用腾讯日线，不在东财上重试以免延长限流
            try:
                return from_em()
            except Exception:
                return _retry(from_tx, f"获取 {code} 行情（东财、腾讯均失败）")

        return self.cache.get_json("prices", f"{code}:{s}:{e}", PRICES_TTL, fetch)
