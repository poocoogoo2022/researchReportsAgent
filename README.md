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

`reports` 和 `digest --max-reads 0` 不需要 API Key。要生成正文归纳或使用 `ask`，请在项目根目录将 `.env.example` 复制为 `.env`（如果已有 `.env`，直接编辑），把 `RRA_API_KEY` 替换为真实的 Key。不要把 Key 粘贴到聊天或提交到 Git。

LLM 使用 OpenAI 兼容接口，默认 DeepSeek（`deepseek-chat`）。改 `RRA_BASE_URL` 和 `RRA_MODEL` 可以换成其他支持 tool calling 的兼容服务。

## 用法

```bash
# 研报列表 + 评级统计 + EPS 一致预期（不调用 LLM，不需要 API Key）
rra reports 600519 --days 30

# 生成完整解读，保存为 Markdown
rra digest 600519 --days 60 -o reports/600519.md

# 只生成统计 Markdown，不读取正文、不调用模型
rra digest 600519 --days 60 --max-reads 0 -o reports/600519-stats.md

# 自由提问
rra ask 600519 "各家对直销渠道占比的判断有什么不同？"
```

`--max-reads` 控制正文读取上限（默认 6）；`ask --max-steps` 控制问答的工具调用轮数（默认 12）。`digest` 使用固定流程，不再需要 `--max-steps`。

示例：[研报清单与统计](examples/reports-600519.txt) · [贵州茅台研报解读（真实 DeepSeek 输出的校订节选）](examples/digest-600519.md)。

## 架构

```
CLI
├─ reports → data.py + analysis.py → 列表与统计
├─ digest  → digest.py → 固定统计表 + 带出处的正文归纳 → Markdown
│                          └─ 有可读正文时，一次模型调用，不开放工具
└─ ask     → agent.py + tools.py ↔ LLM → 自由问答

共享模块：data.py（akshare）、analysis.py（纯计算）、pdf.py（正文抽取）、cache.py（文件缓存）
```

设计要点：

- `digest` 的评级、EPS 和涨跌幅表都由程序直接生成，不由模型复述。模型只归纳正文节选；程序检查引用 ID 是否属于已读样本，再填入机构、日期与 PDF 链接。引用可追溯不等于模型对原文的解释已经过核验。
- `digest` 在行情或正文不可用时标明缺项；模型请求失败或返回无效结构时不会覆盖已有报告。
- `ask` 保留工具调用循环，工具错误作为结果交回模型处理，达到轮数上限后要求模型基于已有信息作答。
- 成本控制：正文截断、限制读取篇数、缓存 PDF 正文。

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
