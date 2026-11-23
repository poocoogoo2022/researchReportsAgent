"""固定流程生成研报解读：程序计算统计，模型只归纳已读正文。"""

from __future__ import annotations

import json
import re
from datetime import date
from html import escape
from typing import Any, Callable
from urllib.parse import quote

from . import analysis
from .data import DataError, MarketData, normalize_code
from .llm import LLMClient
from .pdf import ReportReader
from .prompts import DIGEST_SYSTEM

_SECTIONS = {"themes": "核心逻辑", "differences": "分歧点", "risks": "风险提示"}


def _inline(value: Any) -> str:
    text = escape(" ".join(str(value).split()), quote=False)
    return re.sub(r"([\\`*_\[\]|~])", r"\\\1", text)


def _table(headers, rows) -> str:
    return "\n".join("| " + " | ".join(_inline(v) for v in row) + " |"
                     for row in (headers, ["---"] * len(headers), *rows))


def _citation(report: dict) -> str:
    label = _inline(f"{report['org']}（{report['date']}）")
    url = quote(report["pdf_url"], safe=":/?=&%+@,;#")
    return f"[{label}]({url})"


def _render_statistics(reports: list[dict], returns: list[dict] | None) -> list[str]:
    ratings = analysis.rating_summary(reports)
    sections = [
        "## 覆盖概况",
        f"区间内有 {ratings['org_count']} 家机构发布 {ratings['report_count']} 份研报。评级分布按各机构的最新东财评级统计。",
        _table(["东财评级", "机构数"], ratings["distribution"].items()),
        "评级变化仅比较同机构在区间内最新两份研报；不可比较不代表首次覆盖。",
        _table(["机构", "列表日期", "最新评级", "前次评级", "区间内变化"], [
            (c["org"], c["date"], c["rating"] or "无评级", c["prev_rating"] or "—",
             "无前次可比较" if c["action"] == "首次覆盖(区间内)" else c["action"])
            for c in ratings["changes"]
        ]),
        "## 盈利预测一致预期",
    ]
    eps = analysis.eps_consensus(reports)
    if eps:
        sections.extend([
            "每家机构只取区间内最新一份研报，EPS 单位为元/股。预测值不代表已实现业绩。",
            _table(["年份", "样本数", "均值", "中位数", "最高（机构）", "最低（机构）", "变异系数"], [
                (year, s["n"], s["mean"], s["median"],
                 f"{s['max']['eps']}（{s['max']['org']}）", f"{s['min']['eps']}（{s['min']['org']}）",
                 s["cv"] if s["cv"] is not None else "—")
                for year, s in eps.items()
            ]),
        ])
    else:
        sections.append("区间内没有可用的 EPS 预测。")
    sections.append("## 研报发布后股价表现")
    if returns is None:
        sections.append("日线行情暂不可用，未计算研报发布后的涨跌幅。")
    else:
        sections.extend([
            "前复权累计涨跌幅（%），基准为列表日期当天或此前最近交易日的收盘价。缺数据不视为零；价格变化不代表研报导致。",
            _table(["机构", "列表日期", "1 个交易日", "5 个交易日", "20 个交易日"], [
                (r["org"], r["date"], *(
                    "缺数据" if r[key] is None else f"{r[key]:.2f}" for key in ("ret_1d", "ret_5d", "ret_20d")
                ))
                for r in returns
            ]),
        ])
    return sections


def _render_findings(content: str | None, excerpts: dict[str, dict]) -> list[str]:
    if not content or not content.strip():
        raise DataError("模型未返回正文，未生成报告")
    text = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    try:
        data = json.loads(fence[1] if fence else text)
    except ValueError as exc:
        raise DataError("模型未返回有效的正文 JSON，未生成报告") from exc
    if not isinstance(data, dict) or set(data) != set(_SECTIONS) or any(not isinstance(v, list) for v in data.values()):
        raise DataError("模型返回的正文结构不符合要求，未生成报告")

    rendered = []
    for key, heading in _SECTIONS.items():
        lines = []
        for item in data[key][:4]:
            if not isinstance(item, dict):
                continue
            text, ids = item.get("text"), item.get("sources")
            if not isinstance(text, str) or not text.strip() or len(text) > 240 or len(text.splitlines()) != 1:
                continue
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i in excerpts for i in ids):
                continue
            if re.search(r"https?://", text, re.IGNORECASE):
                continue
            refs = "、".join(_citation(excerpts[i]) for i in dict.fromkeys(ids))
            lines.append(f"- {_inline(text.strip())}（来源：{refs}）")
        rendered.extend([f"### {heading}", "\n".join(lines) or "已读节选未提供可引用的要点。"])
    return rendered


def build_digest(
    market: MarketData,
    reader: ReportReader,
    make_llm: Callable[[], LLMClient],
    code: str,
    days: int,
    today: date,
    max_reads: int,
    log: Callable[[str], None] | None = None,
) -> str:
    code = normalize_code(code)
    reports = market.list_reports(code, days, today=today)
    name = reports[0]["name"] if reports else ""
    label = f"{_inline(name)}（{code}）" if name else code
    sections = [f"# {label} 研报解读 — {today}", f"回看窗口：截至 {today}，最近 {days} 天（按 akshare 研报列表日期）。"]
    if not reports:
        return "\n\n".join([*sections, "区间内没有可用研报。"])

    try:
        prices = market.price_history_for_reports(code, reports, today)
    except DataError:
        prices = []
    returns = analysis.post_report_performance(reports, prices) if prices else None
    sections.extend(_render_statistics(reports, returns))

    excerpts = {}
    attempts = 0
    # 每个机构只挑最新一份；代码选择样本，模型无法扩大请求范围。
    candidates = sorted(analysis.latest_by_org(reports).values(), key=lambda r: r["date"], reverse=True)
    for r in candidates:
        if attempts >= max_reads:
            break
        if not r["pdf_url"].startswith("https://pdf.dfcfw.com/"):
            continue
        attempts += 1
        try:
            text = reader.read(r["pdf_url"], max_chars=5000)
        except DataError:
            continue
        excerpts[r["report_id"]] = {**r, "text": text}

    sections.append("## 正文归纳（AI）")
    if max_reads == 0:
        sections.append("本次只生成统计，未读取研报正文。")
    elif not excerpts:
        sections.append("未能读取可用的研报正文，本次仅展示统计。")
    else:
        sections.append(f"仅依据已读取的 {len(excerpts)} 份正文节选（尝试 {attempts} 份），不代表全部研报。")
        payload = [{k: r[k] for k in ("report_id", "org", "date", "title", "text")} for r in excerpts.values()]
        result = make_llm().chat([
            {"role": "system", "content": DIGEST_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ], None)
        if log:
            log(f"  正文归纳：{len(excerpts)} 份节选，token 用量 {result.usage}")
        sections.extend(_render_findings(result.content, excerpts))

    sections.extend([
        "## 数据来源与免责声明",
        "统计由程序根据 akshare 的研报列表和前复权日线生成。正文归纳为 AI 对所引节选的整理。本文不构成投资建议。",
    ])
    return "\n\n".join(sections)
