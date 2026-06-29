# grok-search

> AI-agent web research CLI — Grok 子代理调研 + 多源补源（Brave / 百度 / News / Serper / Tavily）

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Self-contained](https://img.shields.io/badge/no_external_CLI-green.svg)](#)

## 这是什么

`grok-search` 是一个**研究工具**——给 Grok（xAI 4.20 系列，内部 4-16 agent 并行辩论）+ 多家搜索 API 套一个壳，让调用方可以：

- **让 Grok 当子代理调研一个主题**（单 agent 模式）
- **并行让多个 Grok 调研不同方向**（调用方自行编排，不需要 CLI 封装）
- **按需 fetch 关键 URL 验证 Grok 答案**（调用方按需，CLI 不替 AI 做判断）

**核心理念**：CLI 暴露原料（搜索结果、Grok 答案、来源 URL），**不替调用 AI 做决策**。抓哪些 URL 验证、要不要并行多次 search、怎么合成最终答案——都是调用 AI 的责任。

## 快速开始（5 分钟）

```bash
# 1. 克隆
git clone https://github.com/peng13071347666-crypto/grok-search-new.git
cd grok-search-new

# 2. 安装依赖
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. 链接到 PATH
mkdir -p ~/.local/bin
ln -s "$(pwd)/bin/grok-search" ~/.local/bin/grok-search
export PATH="$HOME/.local/bin:$PATH"

# 4. 配置 Grok API
mkdir -p ~/.config/grok-search
cat > ~/.config/grok-search/config.json << 'EOF'
{
  "OPENAI_COMPATIBLE_API_URL": "https://your-grok-proxy.com/v1",
  "OPENAI_COMPATIBLE_API_KEY": "sk-your-key-here",
  "OPENAI_COMPATIBLE_MODEL": "grok-4.20-multi-agent-xhigh",
  "primary_api_mode": "chat-completions"
}
EOF

# 5. 验证
grok-search doctor
```

跑通上面就装好了。

## 完整安装

### 先决条件

- **Python 3.10+**（项目用 `httpx` 异步 + `match` 语法）
- 一个 **OpenAI-compatible Grok API endpoint**（比如 https://api.x.ai/v1 或任何中转站）
- 可选：补源 API Key（Brave / 百度千帆 / News API / Serper / Tavily）

### 从源码安装

```bash
git clone https://github.com/peng13071347666-crypto/grok-search-new.git
cd grok-search-new
python3 -m venv .venv
.venv/bin/pip install -e .
```

### 链接到 PATH

```bash
# macOS / Linux
mkdir -p ~/.local/bin
ln -sf "$(pwd)/bin/grok-search" ~/.local/bin/grok-search
export PATH="$HOME/.local/bin:$PATH"

# 永久生效（zsh）
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

### 验证安装

```bash
grok-search --help
# 应显示: search, brave, baidu, news, serper, tavily, fetch, deep, config, doctor

grok-search doctor
# 应显示: 5 个 Grok 模型可被列出（grok-4.20-*）
```

## 配置

### Grok API（必配）

任何 OpenAI-compatible 端点都行——xAI 官方或中转站。

**方式 A：配置文件** `~/.config/grok-search/config.json`

```json
{
  "OPENAI_COMPATIBLE_API_URL": "https://api.x.ai/v1",
  "OPENAI_COMPATIBLE_API_KEY": "xai-...",
  "OPENAI_COMPATIBLE_MODEL": "grok-4.20-multi-agent-xhigh",
  "primary_api_mode": "chat-completions"
}
```

**方式 B：环境变量**

```bash
export OPENAI_COMPATIBLE_API_URL="https://api.x.ai/v1"
export OPENAI_COMPATIBLE_API_KEY="xai-..."
export OPENAI_COMPATIBLE_MODEL="grok-4.20-multi-agent-xhigh"
export PRIMARY_API_MODE="chat-completions"
```

### 补源 API（可选）

不配也能用，只是少了对应路径的补源结果。

**方式 A：配置文件** `~/.config/grok-search/config.json`

```json
{
  "BRAVE_API_KEY": "BSA...",
  "BAIDU_API_KEY": "bce-v3/...",
  "NEWS_API_KEY": "...",
  "SERPER_API_KEY": "...",
  "TAVILY_API_KEY": "tvly-..."
}
```

**方式 B：CLI 配置**

```bash
grok-search config set BRAVE_API_KEY "BSA..."
grok-search config set SERPER_API_KEY "..."
# 等等
```

**方式 C：环境变量**

```bash
export GROK_SEARCH_BRAVE_API_KEY="BSA..."
export GROK_SEARCH_SERPER_API_KEY="..."
```

优先级：环境变量 > 配置文件 > 默认值。

## 使用

### 三档决策树

| 档位 | 适用场景 | 工具 |
|------|---------|------|
| **0 - Simple** | 定义/概念/一句话能答 | `brave/baidu` 搜 → `fetch` |
| **1 - Single Agent** | 单主题/对比两个选项/方向一致 | `search --deep` |
| **2 - Multi Agent** | 3+ 独立对象/跨领域 | 调用 AI 并行 `search` 多次 |

### 档位 0：搜 + 抓取

```bash
# 1. 先用搜索 API 找到候选 URL
grok-search brave|baidu "关键词" --count 5
# 2. 从结果中选 1-2 个最相关的 URL
grok-search fetch "https://最相关的URL" --format json
# 3. 用 fetch 到的原文直接回答用户
```

**不走 Grok**——简单问题不需要多 Agent 辩论，直接 fetch 原文比 Grok 转述更可靠。**最便宜、最准确**，适合"X 是什么"这种查询。

### 档位 1：单 Grok 调研

```bash
# 推荐 Prompt 模板（已在 SKILL.md 里详细说明）
PROMPT='你是信息收集专家，运行在多 Agent 协作模式下。你可使用 web_search 和 x_search 工具从多角度全面收集信息。

你的任务是：调研 2026 年 Cursor 和 GitHub Copilot 的功能差异。

【研究纪律】
1. Start wide, then narrow：先用 2-3 个宽泛 query 摸清信息全貌，再针对关键缺口用具体 query 深入。
2. 不要重复搜索同一关键词。
3. 充分利用 x_search 获取 X/Twitter 上的独家用户反馈。
4. 来源优先级：官方文档/公告 > 独立 benchmark 评测 > 开发者社区反馈 > 营销博客。

【输出规则】
- 每个信息点必须标注来源 URL。
- 不同信息源对同一问题的不同说法都要如实收录，不要选边、不要调和。
- 不需要写结论、推荐或主观评价。
- 如果用户问题模糊，先反问 1-2 个澄清问题，不要猜测。
- 用中文输出。'

# 跑 deep 模式
grok-search search --deep "$PROMPT" \
  --short "Cursor vs GitHub Copilot 2026 features comparison" \
  --intent general \
  --model grok-4.20-multi-agent-xhigh \
  --timeout 180 \
  --format json

# 简单 deep（跳过 Brave/Serper 补源，节省 3-5s）
grok-search search --deep "$PROMPT" \
  --short "Cursor vs GitHub Copilot 2026" \
  --intent general \
  --no-supplement \
  --model grok-4.20-multi-agent-xhigh \
  --format json
```

返回 JSON 关键字段：

| 字段 | 含义 |
|------|------|
| `content` | Grok 子代理的调研结果（**原料**，不是最终答案） |
| `primary_sources` | Grok 引用的来源 URL 列表 |
| `brave_sources` / `intent_sources` | 补源 API 结果（未 `--no-supplement` 时有） |
| `content_disclaimer` | "content 是原料，调用 AI 必须自行验证" |
| `supplement_skipped` | 是否跳过了补源（true 表示用了 `--no-supplement`） |

### 档位 2：多 Grok 并行

**不在 CLI 封装**——调用 AI 用 `asyncio.gather` 或 `Promise.all` 并行多次 `grok-search search` 即可。

```python
# Python 示例
import asyncio
import json
import subprocess

async def grok_search(query, **kwargs):
    return json.loads(subprocess.check_output(
        ["grok-search", "search", "--deep", query, "--format", "json", *kwargs]
    ))

async def main():
    # 并行 2 个 subject 调研
    results = await asyncio.gather(
        grok_search("调研 Cursor 2026 功能", --short="Cursor features 2026", intent="general"),
        grok_search("调研 GitHub Copilot 2026 功能", --short="GitHub Copilot features 2026", intent="general"),
    )
    # 调用 AI 自己合成对比
    return results
```

### 补源搜索

```bash
# 独立使用各家搜索 API
grok-search brave "query" --count 5
grok-search baidu "查询" --count 5
grok-search serper "query" --count 5
grok-search news "breaking news" --count 5
grok-search tavily "query" --count 5
```

### 配置管理

```bash
grok-search config list
grok-search config get BRAVE_API_KEY
grok-search config set BRAVE_API_KEY "BSA..."
grok-search config unset BRAVE_API_KEY
```

## 命令参考

```
grok-search [--format json|markdown] <子命令>

子命令：
  search          Grok 搜索（简单或 --deep 深度模式）
    --deep             启用深度模式（3 路并行：Grok + Brave + 意图补源）
    --short KEYWORDS   补源搜索关键词（--deep 时必填）
    --intent {chinese|news|general}
                       补源意图路由
    --no-supplement    跳过 Brave + 意图补源
    --model MODEL      指定 Grok 模型
    --timeout SECONDS  Grok 调用超时

  brave|baidu|news|serper|tavily
                  独立使用各搜索 API
    --count N          返回结果数（默认 5）

  fetch URL       抓取单个 URL 原文（Jina Reader → httpx → Tavily 兜底）
  deep QUERY      离线规划器（质检参考，不发起真实请求）
  config          配置管理（set|get|list|unset）
  doctor          配置检查 + 模型预检
```

## 作为 pi skill 安装（可选）

如果你是 [pi](https://pi.dev) 用户，想让 pi 在合适场景自动调用这个工具：

```bash
# 把 SKILL.md 软链接到 pi 的 skills 目录
ln -s "$(pwd)/SKILL.md" ~/.pi/agent/skills/grok-search/SKILL.md

# 验证
ls -la ~/.pi/agent/skills/grok-search/
```

pi 会自动读取 `SKILL.md` 的 description 和内容，让模型在合适场景自动调用 `grok-search` CLI。

**SKILL.md 关键设计**：
- **3 档决策树**：模型按任务复杂度选档位
- **Prompt E 模板**：让 Grok "不写结论、收录不同说法、反问不猜测"
- **不自动改写用户原话**：模型拿用户原话给 Grok，Grok 自己反问
- **content 是原料不是答案**：模型必须自己 fetch 验证

完整设计哲学见 [REFACTOR_PLAN.md](REFACTOR_PLAN.md)。

## 架构

```
grok-search (Python CLI)
  │
  ├─ grok_search 模块
  │    └─ OpenAI-compatible 客户端 → Grok API (4-16 agent 内部辩论)
  │
  ├─ httpx → Brave Search API (英文/通用补源)
  ├─ httpx → 百度千帆 API (中文补源)
  ├─ httpx → News API (--intent news 时用)
  ├─ httpx → Serper (Google) API (默认补源)
  └─ httpx → Tavily API (Brave 失败兜底 + fetch 第三级)

fetch 链路：
  Jina Reader (免费, 无限量, 返回干净 Markdown)
    → httpx (HTML 提取)
      → Tavily/Firecrawl (兜底)
```

**完全自包含**——`grok_search` 模块是 Python 包，`grok_search.py` 直接 `import` 调用，**不依赖外部 grok-search CLI**。

## 故障排查

### `grok-search doctor` 显示模型列表为空

```bash
# 检查配置
cat ~/.config/grok-search/config.json

# 测试 API
curl -H "Authorization: Bearer $YOUR_KEY" "https://your-proxy.com/v1/models"
```

### `grok-search search` 返回 401/403

API Key 错了或过期。`grok-search config set` 重新设置。

### `grok-search fetch` 抓取失败

Jina Reader 可能被限流。自动 fallback 到 httpx，再 fallback 到 Tavily。如果三个都失败，看具体错误。

### `grok-search search --deep` 跑 3 分钟还没结果

Grok 那边可能慢。`--timeout` 默认 180s。可用 `--no-supplement` 减少并发。

### macOS 上 Python 3.10 找不到

```bash
brew install python@3.10
# 或用 pyenv
pyenv install 3.10
```

## 开发

```bash
# 开发模式安装
.venv/bin/pip install -e ".[dev]"

# 跑测试
.venv/bin/pytest

# 提交改动
git checkout -b feature/your-feature
git commit -m "feat: ..."
git push origin feature/your-feature
```

## License

MIT — see [LICENSE](LICENSE).

## 相关链接

- [SKILL.md](SKILL.md) — pi skill 描述（3 档决策树 + Prompt E 模板）
- [REFACTOR_PLAN.md](REFACTOR_PLAN.md) — 设计哲学（为什么这么改）
- [Grok 4.20 multi-agent 文档](https://docs.x.ai/developers/model-capabilities/text/multi-agent) — 4-16 agent 内部架构
- [Anthropic multi-agent 研究](https://www.anthropic.com/engineering/multi-agent-research-system) — 业界参考

---

**TL;DR**：`git clone` → `pip install -e .` → 配置 API Key → `grok-search doctor` → 开始用。**CLI 不替调用 AI 做决策**——这是核心设计原则。
