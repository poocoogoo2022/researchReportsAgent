"""暴露给 LLM 的工具：JSON schema 定义 + 执行分发。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from . import analysis
from .data import DataError, MarketData
from .pdf import ReportReader

MAX_RESULT_CHARS = 12000


def _schema(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


_CODE = {"type": "string", "description": "6 位 A 股代码，如 600519"}
_DAYS = {"type": "integer", "description": "回看自然日天数，默认 90", "minimum": 1, "maximum": 730}

TOOL_SCHEMAS = [
    _schema("list_reports", "列出近期券商研报元数据（标题、机构、评级、日期、EPS 预测、report_id），不含正文。",
            {"code": _CODE, "days": _DAYS}, ["code"]),
    _schema("read_report", "读取一份研报的正文文本（已截断）。report_id 来自 list_reports。",
            {"code": _CODE, "report_id": {"type": "string"},
             "max_chars": {"type": "integer", "description": "最多返回字数，默认 6000", "minimum": 500, "maximum": 20000}},
            ["code", "report_id"]),
    _schema("get_stock_info", "获取股票基本信息：最新价、市值、行业。", {"code": _CODE}, ["code"]),
    _schema("get_rating_summary", "统计评级分布（按机构最新评级）与各机构评级变化。", {"code": _CODE, "days": _DAYS}, ["code"]),
    _schema("get_eps_consensus", "按年份计算各机构最新 EPS 预测的一致预期：均值、中位数、最高、最低、变异系数。",
            {"code": _CODE, "days": _DAYS}, ["code"]),
    _schema("get_post_report_performance", "每份研报发布后 1/5/20 个交易日的累计涨跌幅（%，前复权）。",
            {"code": _CODE, "days": _DAYS}, ["code"]),
]


def _brief(r: dict[str, Any]) -> dict[str, Any]:
    return {k: r[k] for k in ("report_id", "date", "org", "rating", "title", "forecasts")}


class Toolkit:
    def __init__(self, market: MarketData, reader: ReportReader, today: date | None = None, max_reads: int = 6):
        self.market = market
        self.reader = reader
        self.today = today or date.today()
        self.max_reads = max_reads
        self.reads = 0

    # --- 工具实现 ---
    def list_reports(self, code: str, days: int = 90) -> list[dict[str, Any]]:
        return [_brief(r) for r in self.market.list_reports(code, days, today=self.today)]

    def read_report(self, code: str, report_id: str, max_chars: int = 6000) -> dict[str, Any]:
        if self.reads >= self.max_reads:
            return {"error": f"本次已读取 {self.max_reads} 份研报，达到上限，请基于已有信息作答"}
        r = self.market.find_report(code, report_id)
        text = self.reader.read(r["pdf_url"], max_chars=max_chars)
        self.reads += 1
        return {**_brief(r), "text": text}

    def get_stock_info(self, code: str) -> dict[str, Any]:
        return self.market.stock_info(code)

    def get_rating_summary(self, code: str, days: int = 90) -> dict[str, Any]:
        return analysis.rating_summary(self.market.list_reports(code, days, today=self.today))

    def get_eps_consensus(self, code: str, days: int = 90) -> dict[str, Any]:
        return analysis.eps_consensus(self.market.list_reports(code, days, today=self.today))

    def get_post_report_performance(self, code: str, days: int = 90) -> list[dict[str, Any]]:
        reports = self.market.list_reports(code, days, today=self.today)
        if not reports:
            return []
        start = date.fromisoformat(min(r["date"] for r in reports)) - timedelta(days=10)
        prices = self.market.price_history(code, start, self.today)
        return analysis.post_report_performance(reports, prices)

    # --- 分发 ---
    def call(self, name: str, arguments: str | dict[str, Any]) -> str:
        """执行工具并返回字符串结果。所有错误都转为文本返回给模型。"""
        fn = getattr(self, name, None) if name in {s["function"]["name"] for s in TOOL_SCHEMAS} else None
        if fn is None:
            return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
            if not isinstance(args, dict):
                raise ValueError("参数必须是 JSON 对象")
            result = fn(**args)
        except DataError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            return json.dumps({"error": f"参数错误：{e}"}, ensure_ascii=False)
        text = json.dumps(result, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "…（结果过长已截断，可缩小 days）"
        return text
