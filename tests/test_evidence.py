import json

import pytest

from rra.digest import _render_findings
from rra.evidence import single_period


# 简化的测试夹具，保留线上错比涉及的报告期、方向和数值。
PACIFIC = "26Q1-Q3经营活动现金流为 840.59 亿元，\n同比增长 120.07%。"
KAIYUAN = "26Q3经营性现金流为 133.68 亿元，同比下降 46.69%。"
EXCERPTS = {
    "pacific": {"org": "太平洋", "date": "2026-11-13", "pdf_url": "https://pdf.dfcfw.com/p.pdf", "text": PACIFIC},
    "kaiyuan": {"org": "开源证券", "date": "2026-11-03", "pdf_url": "https://pdf.dfcfw.com/k.pdf", "text": KAIYUAN},
}


def source(id_, quote, period):
    return {"report_id": id_, "quote": quote, "period": period}


def render(section, sources, excerpts=EXCERPTS):
    payload = {"themes": [], "differences": [], "risks": []}
    payload[section].append({"text": "待检验的要点", "sources": sources})
    return "\n".join(_render_findings(json.dumps(payload), excerpts))


@pytest.mark.parametrize(("text", "expected"), [
    ("26Q3单季", "2026Q3"),
    ("2026 年第三季度", "2026Q3"),
    ("2026年三季度单季", "2026Q3"),
    ("2026年三季度", None),
    ("2026年三季度累计", "2026Q1-Q3"),
    ("2026Q1–Q3", "2026Q1-Q3"),
    ("26Q1-3", "2026Q1-Q3"),
    ("2026 年前三季度", "2026Q1-Q3"),
    ("2026年前9个月", "2026Q1-Q3"),
    ("2026年上半年", "2026Q1-Q2"),
    ("2026年度", "2026FY"),
    ("2026全年", "2026FY"),
    ("FY2026", None),
    ("2026FY", "2026FY"),
    ("26Q3相较26Q2改善", None),
    ("26Q2-Q3", None),
    ("2026年前三季度经营现金流增加，但Q3同比下降", None),
    ("Q3单季", None),
    ("2026年发布的研报", None),
])
def test_period_requires_unambiguous_scope_and_year(text, expected):
    assert single_period(text) == expected


@pytest.mark.parametrize("declared", ["2026Q1-Q3", "2026Q3", None])
def test_real_cash_flow_regression_rejects_comparing_year_to_date_with_single_quarter(declared):
    sources = [source("pacific", PACIFIC, declared), source("kaiyuan", KAIYUAN, "2026Q3")]
    assert "待检验的要点" not in render("differences", sources)


def test_same_period_comparison_renders_matched_quotes_and_period():
    first = "2026 年第三季度经营性现金流为 140.00 亿元，\n同比下降 44.00%。"
    excerpts = {**EXCERPTS, "pacific": {**EXCERPTS["pacific"], "text": first}}
    result = render("differences", [source("pacific", first.replace("\n", "  "), "2026Q3"),
                                    source("kaiyuan", KAIYUAN, "2026Q3")], excerpts)
    assert "待检验的要点" in result
    assert "（报告期：2026Q3）：「2026 年第三季度经营性现金流为 140.00 亿元， 同比下降 44.00%。」" in result
    assert "[开源证券（2026-11-03）](https://pdf.dfcfw.com/k.pdf)（报告期：2026Q3）" in result


@pytest.mark.parametrize("sources", [
    [source("pacific", PACIFIC.replace("120.07", "120.70"), "2026Q1-Q3")],
    [source("kaiyuan", PACIFIC, "2026Q1-Q3")],
    [source("unknown", PACIFIC, "2026Q1-Q3")],
    [source("pacific", PACIFIC, "2026Q1-Q3"), source("kaiyuan", "模型补写的原文节选", None)],
    ["pacific"],
])
def test_rejects_quotes_not_in_the_claimed_excerpt(sources):
    assert "待检验的要点" not in render("themes", sources)


def test_no_dated_period_allowed_for_a_risk_but_not_a_comparison():
    risk = "风险提示：终端需求或不及预期。"
    excerpts = {id_: {**data, "text": risk} for id_, data in EXCERPTS.items()}
    sources = [source(id_, risk, None) for id_ in excerpts]
    assert "报告期：未识别" in render("risks", sources, excerpts)
    assert "待检验的要点" not in render("differences", sources, excerpts)


def test_comparison_requires_two_distinct_institutions():
    excerpts = {id_: {**data, "org": "同一机构", "text": KAIYUAN} for id_, data in EXCERPTS.items()}
    sources = [source(id_, KAIYUAN, "2026Q3") for id_ in excerpts]
    assert "待检验的要点" not in render("differences", sources, excerpts)
