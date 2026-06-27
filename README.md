# grok-search

基于 Grok AI Agent 主搜索 + 多源补源的智能搜索 CLI。Grok 作为子代理执行调研任务，Brave/百度/News/Serper 作为搜索 API 补源。

## 架构

```
用户问题
  → grok-search search --deep "给Grok的调研任务" --keywords "关键词" --intent general
       ├─ ① Grok 子代理调研（smart-search 透传）  → content（主回答）
       ├─ ② Brave 补源（失败 → Tavily 兜底）      → brave_sources
       └─ ③ 意图补源（百度/News/Serper 按 intent） → intent_sources
  → grok-search fetch URL 核实关键声明
  → 最终答案
```

## 前置依赖

- **Python 3.9+** + `httpx`
- **[smart-search](https://github.com/anthropics/smart-search) CLI**（Grok 主搜索，需单独安装配置）
- 补源 API Key（可选，不配置则对应补源路径为空）

## 安装

```bash
# 1. 克隆仓库
git clone https://github.com/peng13071347666-crypto/grok-search-new.git
cd grok-search-new

# 2. 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install httpx

# 3. 链接到 PATH（可选）
ln -s "$(pwd)/bin/grok-search" ~/.local/bin/grok-search
```

## 配置

配置文件位于 `~/.config/grok-search/config.json`，支持以下 Key：

| Key | 说明 | 默认 API URL |
|-----|------|-------------|
| `BRAVE_API_KEY` | Brave Search API Key | `https://api.search.brave.com/res/v1` |
| `BAIDU_API_KEY` | 百度千帆 API Key | `https://qianfan.baidubce.com/v2/ai_search/web_search` |
| `BAIDU_SECRET_KEY` | 百度千帆 Secret Key | - |
| `NEWS_API_KEY` | News API Key | `https://newsapi.org/v2` |
| `SERPER_API_KEY` | Serper (Google) API Key | `https://google.serper.dev/search` |
| `TAVILY_API_KEY` | Tavily API Key（Brave 失败兜底） | `https://api.tavily.com` |

两种配置方式：

```bash
# 方式1：命令行配置
grok-search config set BRAVE_API_KEY "BSAb..."

# 方式2：环境变量
export GROK_SEARCH_BRAVE_API_KEY="BSAb..."
```

智能读取 `~/.config/smart-search/config.json` 中的 Tavily Key（可复用 smart-search 已配置的 Key）。

## 使用

### 简单搜索（透传 smart-search）

```bash
smart-search search "什么是 WebAssembly？" --model grok-4.20-multi-agent-console --timeout 120
```

### 深度搜索（三路并行：Grok + Brave + 意图补源）

```bash
grok-search search --deep \
  "你是资深开发者工具分析师，可自主使用 web_search、X/Twitter 搜索等工具进行独立调研。

你的任务是：调研 2026 年 Cursor 和 GitHub Copilot 的对比。

请自主决定研究方法、搜索策略和分析框架。每个事实性断言标注来源 URL。

请用中文输出。" \
  --keywords "Cursor vs GitHub Copilot 2026 comparison" \
  --intent general \
  --model grok-4.20-multi-agent-xhigh \
  --timeout 180 \
  --format json
```

### 补源搜索（独立使用）

```bash
grok-search brave "Cursor vs Copilot 2026" --count 5
grok-search baidu "Cursor和Copilot对比" --count 5
grok-search news "AI coding assistant 2026" --count 5
grok-search serper "Cursor vs GitHub Copilot" --count 5
```

### 网页抓取核实

```bash
grok-search fetch "https://cursor.com/pricing"
```

### 配置检查

```bash
grok-search doctor
```

## 命令参考

```
grok-search [--format json|markdown] <子命令>

子命令：
  search    搜索（支持 --deep 深度模式）
  brave     独立 Brave 搜索
  baidu     独立百度搜索
  news      独立 News API 搜索
  serper    独立 Serper (Google) 搜索
  tavily    独立 Tavily 搜索
  fetch     网页抓取核实
  deep      离线规划器（质检参考）
  config    配置管理（set|get|list|unset）
  doctor    配置检查
```

## 深度搜索 JSON 输出字段

| 字段 | 说明 |
|------|------|
| `content` | Grok 子代理的回答正文 |
| `primary_sources` | Grok 引用的来源 |
| `brave_sources` | Brave 补源候选 URL |
| `intent_sources` | 意图补源候选 URL |
| `extra_sources` | 合并去重后的全部补源 URL |
| `source_warning` | 补源警告（需 fetch 核实） |
| `deep_mode` | 固定 `true` |
| `intent` | 使用的意图补源类型 |

## Intent 选择

| intent | 使用 API | 适用场景 |
|--------|---------|---------|
| `chinese` | 百度千帆 | 中文/国内/政策/国产技术 |
| `news` | News API | 新闻/时效事件 |
| `general` | Serper (Google) | 英文/技术/通用搜索 |

## 失败处理

- **Grok 超时**：重试一次，仍失败则降级 fetch 关键 URL
- **Brave 失败**：自动 Tavily 兜底
- **意图补源失败**：不影响 Grok 回答，补源部分为空
- **全部超时**：降级 fetch 最相关 1-2 个 URL

## License

MIT