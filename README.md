# researchReportsAgent 研报解读 Agent

输入一只 A 股代码，agent 通过 akshare 拉取近期券商研报，阅读 PDF 正文，结合行情和盈利预测，生成一份研报解读：评级分布与变化、EPS 一致预期与分歧、核心逻辑、风险提示、研报发布后股价表现。也支持针对研报自由提问。

> 内容由 AI 基于公开券商研报生成，不构成投资建议。

## 安装

需要 Python 3.11+。

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
source .venv/bin/activate
```

`reports` 不需要 API Key。要使用 `digest` / `ask`，请在项目根目录将 `.env.example` 复制为 `.env`（如果已有 `.env`，直接编辑），把 `RRA_API_KEY` 替换为真实的 Key。不要把 Key 粘贴到聊天或提交到 Git。

LLM 使用 OpenAI 兼容接口，默认 DeepSeek（`deepseek-chat`）。改 `RRA_BASE_URL` 和 `RRA_MODEL` 可以换成其他支持 tool calling 的兼容服务。

## 用法

```bash
# 研报列表 + 评级统计 + EPS 一致预期（不调用 LLM，不需要 API Key）
rra reports 600519 --days 30

# 生成完整解读，保存为 Markdown
rra digest 600519 --days 60 -o reports/600519.md

# 自由提问
rra ask 600519 "各家对直销渠道占比的判断有什么不同？"
```

常用参数：`--max-reads` 最多阅读几篇正文（默认 6），`--max-steps` 工具调用轮数上限（默认 12），`-q` 不打印工具调用过程。

示例：[研报清单与统计](examples/reports-600519.txt) · [贵州茅台研报解读（真实 DeepSeek 输出的校订节选）](examples/digest-600519.md)。

## 架构

```
CLI (reports / digest / ask)
   │
   ▼
Agent 循环 ──────► LLM（OpenAI 兼容 tool calling，测试中替换为 ScriptedLLM）
   │ tool_calls
   ▼
Toolkit：list_reports / read_report / get_stock_info /
         get_rating_summary / get_eps_consensus / get_post_report_performance
   │
   ├─ data.py      akshare 封装，字段规整，东财行情失败时切腾讯日线
   ├─ pdf.py       研报 PDF 下载、抽文本、截断
   ├─ analysis.py  评级变化、EPS 一致预期、研报后涨跌幅（纯函数）
   └─ cache.py     文件缓存（研报列表 6h，行情 1h，PDF 正文永久）
```

设计要点：

- 统计数字由代码计算后交给模型，提示词要求模型直接引用，减少模型编造数字。
- 工具出错（接口限流、找不到研报、参数错误）时把错误作为文本返回给模型，循环不中断。
- 成本控制：正文截断、单次运行限制阅读篇数、PDF 正文永久缓存。
- 达到步数上限时强制模型基于已有信息作答。

## 数据源

| 用途 | akshare 接口 |
|------|-------------|
| 个股研报 | `stock_research_report_em` |
| 基本信息 | `stock_individual_info_em` |
| 日线行情 | `stock_zh_a_hist_em`，备用 `stock_zh_a_hist_tx` |
| 研报正文 | 东财 PDF（`pdf.dfcfw.com`） |

东财行情接口请求过多会临时限流，期间行情自动改用腾讯日线。

## 测试

```bash
.venv/bin/pytest            # 离线测试，不需要网络和 API Key
.venv/bin/pytest -m network # 访问真实 akshare 接口
```

## License

MIT
