"""对研报列表做纯计算。数字由代码算，避免让 LLM 算。"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

# 东财评级由强到弱
RATING_ORDER = ["买入", "增持", "中性", "减持", "卖出"]


def _rank(rating: str | None) -> int | None:
    return RATING_ORDER.index(rating) if rating in RATING_ORDER else None


def latest_by_org(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """每家机构最新一份研报。reports 可以是任意顺序。"""
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(reports, key=lambda r: r["date"]):
        out[r["org"]] = r
    return out


def rating_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """评级分布（按机构最新评级）与评级变化（同机构最新 vs 上一份）。"""
    by_org: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(reports, key=lambda r: r["date"]):
        by_org.setdefault(r["org"], []).append(r)

    changes = []
    for org, rs in by_org.items():
        cur = rs[-1]
        prev = rs[-2] if len(rs) > 1 else None
        if prev is None:
            action = "首次覆盖(区间内)"
        else:
            a, b = _rank(prev["rating"]), _rank(cur["rating"])
            if a is None or b is None or a == b:
                action = "维持" if prev["rating"] == cur["rating"] else "变更"
            else:
                action = "上调" if b < a else "下调"
        changes.append({
            "org": org, "date": cur["date"], "rating": cur["rating"],
            "prev_rating": prev["rating"] if prev else None, "action": action,
        })
    changes.sort(key=lambda c: c["date"], reverse=True)

    dist = Counter(c["rating"] or "无评级" for c in changes)
    return {
        "report_count": len(reports),
        "org_count": len(by_org),
        "distribution": dict(sorted(dist.items(), key=lambda kv: _rank(kv[0]) if _rank(kv[0]) is not None else 99)),
        "changes": changes,
    }


def eps_consensus(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """按年份汇总各机构最新研报的 EPS 预测。"""
    per_year: dict[str, list[tuple[str, float]]] = {}
    for org, r in latest_by_org(reports).items():
        for year, f in r["forecasts"].items():
            if f.get("eps") is not None:
                per_year.setdefault(year, []).append((org, f["eps"]))

    out = {}
    for year in sorted(per_year):
        vals = [v for _, v in per_year[year]]
        mean = statistics.fmean(vals)
        stdev = statistics.stdev(vals) if len(vals) > 1 else 0.0
        hi = max(per_year[year], key=lambda t: t[1])
        lo = min(per_year[year], key=lambda t: t[1])
        out[year] = {
            "n": len(vals),
            "mean": round(mean, 3),
            "median": round(statistics.median(vals), 3),
            "max": {"org": hi[0], "eps": hi[1]},
            "min": {"org": lo[0], "eps": lo[1]},
            "cv": round(stdev / mean, 4) if mean else None,
        }
    return out


def post_report_performance(
    reports: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    horizons: tuple[int, ...] = (1, 5, 20),
) -> list[dict[str, Any]]:
    """每份研报发布后 N 个交易日的累计涨跌幅（%）。

    基准为发布日当天或之前最近一个交易日的收盘价（研报多在盘后/盘前发布）。
    交易日不足 N 天时该项为 None。
    """
    prices = sorted((p for p in prices if p.get("close") is not None), key=lambda p: p["date"])
    dates = [p["date"] for p in prices]
    out = []
    for r in reports:
        base_idx = None
        for i, d in enumerate(dates):
            if d <= r["date"]:
                base_idx = i
            else:
                break
        row: dict[str, Any] = {"report_id": r["report_id"], "date": r["date"], "org": r["org"], "rating": r["rating"]}
        for h in horizons:
            key = f"ret_{h}d"
            if base_idx is None or base_idx + h >= len(prices):
                row[key] = None
            else:
                base = prices[base_idx]["close"]
                row[key] = round((prices[base_idx + h]["close"] / base - 1) * 100, 2)
        out.append(row)
    return out
