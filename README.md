# grok-search

AI-agent web research CLI — Grok 子代理搜索 + 多源补源（Brave/百度/News/Serper/Tavily）。

**完全自包含**，不依赖外部 smart-search CLI。Grok API 调用内置于 `smart_search` 模块，补源通过 httpx 直接调用。

## 安装

```bash
git clone https://github.com/peng13071347666-crypto/grok-search-new.git
cd grok-search-new

# 创建虚拟环境并安装依赖
python3 -m venv .venv
.venv/bin/pip install httpx rich tenacity

# 链接到 PATH（可选）
ln -s "$(pwd)/bin/grok-search" ~/.local/bin/grok-search
```

## 配置

### Grok API（必配）

编辑 `~/.config/smart-search/config.json`：

```json
{
  "OPENAI_COMPATIBLE_API_URL": "https://your-proxy.com/v1",
  "OPENAI_COMPATIBLE_API_KEY": "sk-xxx",
  "OPENAI_COMPATIBLE_MODEL": "grok-4.20-multi-agent-xhigh",
  "primary_api_mode": "chat-completions"
}
```

### 补源 API（可选，不配则对应路径为空）

编辑 `~/.config/grok-search/config.json` 或设置环境变量 `GROK_SEARCH_<KEY>`：

| Key | 说明 |
|-----|------|
| `BRAVE_API_KEY` | Brave Search |
| `BAIDU_API_KEY` + `BAIDU_SECRET_KEY` | 百度千帆 |
| `NEWS_API_KEY` | News API |
| `SERPER_API_KEY` | Serper (Google) |
| `TAVILY_API_KEY` | Tavily（Brave 失败兜底 + fetch） |

```bash
# 命令行配置
grok-search config set BRAVE_API_KEY "BSAb..."
```

## 使用

### 模型预检

```bash
grok-search doctor
```

### 简单搜索

```bash
grok-search search "什么是 WebAssembly？" --model grok-4.20-multi-agent-console --timeout 120
```

### 深度搜索（三路并行：Grok + Brave + 意图补源）

```bash
grok-search search --deep \
  "你是资深分析师，可自主使用 web_search、X/Twitter 搜索等工具进行独立调研。

你的任务是：调研 2026 年 Cursor 和 GitHub Copilot 的对比。

请自主决定研究方法、搜索策略和分析框架。每个事实性断言标注来源 URL。

请用中文输出。" \
  --keywords "Cursor vs GitHub Copilot 2026 comparison" \
  --intent general \
  --model grok-4.20-multi-agent-xhigh \
  --timeout 180 \
  --format json
```

### 补源搜索

```bash
grok-search brave "query" --count 5
grok-search baidu "query" --count 5
grok-search serper "query" --count 5
```

### 网页抓取核实

```bash
grok-search fetch "https://cursor.com/pricing"
```

### 深度规划器（质检参考）

```bash
grok-search deep "问题"
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
  deep      离线规划器
  config    配置管理（set|get|list|unset）
  doctor    配置检查
```

## Intent 选择

| intent | 使用 API | 适用场景 |
|--------|---------|---------|
| `chinese` | 百度千帆 | 中文/国内/政策 |
| `news` | News API | 新闻/时效事件 |
| `general` | Serper (Google) | 英文/技术/通用 |

## 架构

```
grok-search (Python)
  ├─ smart_search 模块 → Grok API（OpenAI-compatible 中转站）
  ├─ httpx → Brave Search API
  ├─ httpx → 百度千帆 API
  ├─ httpx → News API
  ├─ httpx → Serper (Google) API
  └─ httpx → Tavily API（Brave 兜底）
```

不再依赖外部 smart-search CLI，一个 `pip install` 就能跑。

## License

MIT