"""核对模型引用的原文和显式报告期。不做语义蕴含判断。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 只认常见且带年份的口径，不用研报发布日期猜测年份。
# 先匹配累计（或其它跨度），避免把 26Q1–Q3 的开头识别成单季。
_PERIOD = re.compile(
    r"(?:(?<![0-9])(?P<year>20[0-9]{2}|[0-9]{2})\s*(?:年\s*)?)?(?:"
    r"Q\s*(?P<start>[1-4])\s*[-–—~～至到]\s*Q?\s*(?P<end>[1-4])(?![0-9])"
    r"|(?P<named>上半年|前三季度|前九个月|前[369]个?月|全年|FY(?![A-Za-z0-9])|(?<=年)度)"
    r"|(?:Q\s*(?P<quarter>[1-4])(?![0-9])|(?P<prefix>第|单(?:第)?)?\s*(?P<chinese>[一二三四1-4])\s*季度)"
    r"(?:\s*(?P<scope>累计|单季))?"
    r")",
    re.IGNORECASE,
)
_CUMULATIVE = {"上半年": "Q1-Q2", "前三季度": "Q1-Q3", "前九个月": "Q1-Q3",
               "前3个月": "Q1", "前3月": "Q1", "前6个月": "Q1-Q2", "前6月": "Q1-Q2",
               "前9个月": "Q1-Q3", "前9月": "Q1-Q3", "全年": "FY", "FY": "FY", "度": "FY"}


def single_period(text: str) -> str | None:
    """一个明确期间才返回标准标签。多个期间或不支持的跨度都不推断。"""
    periods = set()
    for m in _PERIOD.finditer(text):
        if not m["year"]:
            return None
        year = m["year"] if len(m["year"]) == 4 else "20" + m["year"]
        if m["start"]:
            if m["start"] != "1" or m["end"] not in {"2", "3", "4"}:
                return None
            suffix = "FY" if m["end"] == "4" else f"Q1-Q{m['end']}"
        elif m["named"]:
            suffix = _CUMULATIVE[m["named"].upper()]
        else:
            # 中文“2026年三季度”未指明是单季还是截至三季度。
            if m["chinese"] and not (m["prefix"] or m["scope"]):
                return None
            q = m["quarter"] or m["chinese"].translate(str.maketrans("一二三四", "1234"))
            suffix = ({"1": "Q1", "2": "Q1-Q2", "3": "Q1-Q3", "4": "FY"}[q]
                      if m["scope"] == "累计" else f"Q{q}")
        periods.add(f"{year}{suffix}")
    return next(iter(periods)) if len(periods) == 1 else None


def normalize_excerpt(text: str) -> str:
    """允许换行与连续空白的差异，其余内容必须逐字匹配。"""
    return " ".join(text.split())


@dataclass(frozen=True)
class Evidence:
    report_id: str
    quote: str
    period: str | None


def validate_sources(value: Any, excerpts: dict[str, dict], *, comparison: bool) -> list[Evidence]:
    """一条要点的任一来源不合格即丢弃整条，避免部分陈述被错误背书。"""
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        return []
    evidence = []
    seen = set()
    for source in value:
        if not isinstance(source, dict) or set(source) != {"report_id", "quote", "period"}:
            return []
        report_id, quote, period = source["report_id"], source["quote"], source["period"]
        if not isinstance(report_id, str) or report_id not in excerpts or report_id in seen:
            return []
        if not isinstance(quote, str):
            return []
        quote = normalize_excerpt(quote)
        if not 8 <= len(quote) <= 240 or quote not in normalize_excerpt(excerpts[report_id]["text"]):
            return []
        if period != single_period(quote):
            return []
        seen.add(report_id)
        evidence.append(Evidence(report_id, quote, period))

    if comparison:
        orgs = {excerpts[e.report_id]["org"].strip() for e in evidence} - {""}
        periods = {e.period for e in evidence}
        if len(orgs) < 2 or None in periods or len(periods) != 1:
            return []
    return evidence
