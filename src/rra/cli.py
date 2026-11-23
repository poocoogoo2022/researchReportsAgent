"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from . import analysis
from .cache import FileCache
from .config import Config, load_dotenv
from .data import DataError, MarketData
from .pdf import ReportReader
from .tools import Toolkit


def _int_range(minimum: int, maximum: int):
    def parse(raw: str) -> int:
        value = int(raw)
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(f"须在 {minimum}–{maximum} 之间")
        return value

    return parse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rra", description="A 股研报解读 Agent（数据来自 akshare）")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("reports", help="列出近期研报与统计（不调用 LLM）")
    r.add_argument("code")
    r.add_argument("--days", type=_int_range(1, 730), default=90)

    d = sub.add_parser("digest", help="生成研报解读报告")
    d.add_argument("code")
    d.add_argument("--days", type=_int_range(1, 730), default=90)
    d.add_argument("-o", "--output", type=Path, help="保存 Markdown 的路径")

    a = sub.add_parser("ask", help="针对某只股票的研报自由提问")
    a.add_argument("code")
    a.add_argument("question")
    a.add_argument("--days", type=_int_range(1, 730), default=90)

    a.add_argument("--max-steps", type=int, default=12, help="问答的工具调用轮数上限")
    for sp in (d, a):
        sp.add_argument("--max-reads", type=_int_range(0, 20), default=6, help="正文读取上限（0–20）；0 不读取正文")
        sp.add_argument("-q", "--quiet", action="store_true", help="不打印执行过程")
    return p


def _fmt(v, digits=2):
    return "-" if v is None else f"{v:.{digits}f}"


def cmd_reports(market: MarketData, code: str, days: int) -> None:
    reports = market.list_reports(code, days)
    if not reports:
        print(f"{code} 最近 {days} 天没有研报")
        return
    print(f"{reports[0]['name']}({code}) 最近 {days} 天研报 {len(reports)} 份\n")
    for r in reports:
        eps = " ".join(f"{y}:{_fmt(f['eps'])}" for y, f in r["forecasts"].items())
        print(f"{r['date']}  {r['org']:<8} {r['rating'] or '-':<4} {r['title']}  [EPS {eps}]")

    s = analysis.rating_summary(reports)
    print(f"\n覆盖机构 {s['org_count']} 家，评级分布：" + "，".join(f"{k} {v}" for k, v in s["distribution"].items()))
    moves = [c for c in s["changes"] if c["action"] in ("上调", "下调")]
    for c in moves:
        print(f"  {c['date']} {c['org']} {c['action']}：{c['prev_rating']} → {c['rating']}")

    print("\nEPS 一致预期（各机构最新一份）：")
    for year, c in analysis.eps_consensus(reports).items():
        print(f"  {year}: 均值 {c['mean']:.2f}  中位 {c['median']:.2f}  "
              f"最高 {c['max']['eps']:.2f}({c['max']['org']})  最低 {c['min']['eps']:.2f}({c['min']['org']})  "
              f"n={c['n']}  CV={_fmt(c['cv'], 3)}")


def cmd_agent(args, cfg: Config, toolkit: Toolkit) -> int:
    api_key = (cfg.api_key or "").strip()
    stats_only = args.command == "digest" and args.max_reads == 0
    if not stats_only and (not api_key or api_key == "sk-xxxxxxxxxxxxxxxxxxxxxxxx"):
        print("请在本项目的 .env 中设置有效的 RRA_API_KEY（参见 .env.example）", file=sys.stderr)
        return 2

    from openai import APIConnectionError, APIError, APIStatusError, AuthenticationError

    from .agent import Agent, print_step
    from .digest import build_digest
    from .llm import OpenAICompatClient
    from .prompts import ASK_TASK, SYSTEM

    def make_llm():
        return OpenAICompatClient(api_key, cfg.base_url, cfg.model)

    try:
        if args.command == "digest":
            answer = build_digest(
                toolkit.market, toolkit.reader, make_llm, args.code, args.days, toolkit.today, args.max_reads,
                log=None if args.quiet else lambda msg: print(msg, file=sys.stderr),
            )
        else:
            agent = Agent(make_llm(), toolkit, SYSTEM.format(today=toolkit.today), max_steps=args.max_steps,
                          on_step=None if args.quiet else print_step)
            task = ASK_TASK.format(code=args.code, days=args.days, question=args.question)
            result = agent.run(task)
            answer = result.answer
            if not args.quiet:
                print(f"  工具调用 {len(result.steps)} 次，token 用量 {result.usage}", file=sys.stderr)
    except AuthenticationError:
        print("模型服务鉴权失败，请检查 RRA_API_KEY 和 RRA_BASE_URL 是否匹配", file=sys.stderr)
        return 1
    except APIConnectionError:
        print("无法连接模型服务，请检查网络及 RRA_BASE_URL 后重试", file=sys.stderr)
        return 1
    except APIStatusError as e:
        print(f"模型服务请求失败（HTTP {e.status_code}），请检查额度、模型配置或稍后重试", file=sys.stderr)
        return 1
    except APIError:
        print("模型服务返回异常，请检查接口兼容性或稍后重试", file=sys.stderr)
        return 1
    if not answer.strip():
        print("模型未返回正文，未生成报告", file=sys.stderr)
        return 1
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(answer + "\n", encoding="utf-8")
        print(f"已保存到 {args.output}", file=sys.stderr)
    print(answer)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    cfg = Config.from_env()
    cache = FileCache(cfg.cache_dir)
    market = MarketData(cache)
    try:
        if args.command == "reports":
            cmd_reports(market, args.code, args.days)
            return 0
        toolkit = Toolkit(market, ReportReader(cache), today=date.today(), max_reads=args.max_reads)
        return cmd_agent(args, cfg, toolkit)
    except DataError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
