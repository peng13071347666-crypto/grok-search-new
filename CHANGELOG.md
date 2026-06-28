# Changelog

所有对 grok-search 的重要变更都会记录在这里。

## [Unreleased] - 2026-06-29

### 重大改动

#### SKILL.md 完全重写
- **3 档决策树**：Simple（不上 Grok）/ Single Agent / Multi Agent
- **Prompt E 模板**：让 Grok "不写结论、收录不同说法、反问不猜测"
- **不自动改写用户原话原则**：保留用户模糊性，让 Grok 自己反问
- **content 是原料不是答案**：多处强调 + `content_disclaimer` 字段

#### grok_search.py 优化
- ✅ 新增 `--no-supplement` 参数：跳过 Brave + 意图补源，节省 3-5s
- ✅ 新增 `supplement_skipped` 字段：标记是否跳过补源
- ✅ 新增 `content_disclaimer` 字段：提示 content 是原料不是答案
- ✅ fetch 改用 Jina Reader（免费无限量，不再消耗 Tavily 配额）
- ✅ 修复 `source_warning` 文案 bug：no_supplement 时正确显示"补源已跳过"
- ✅ 修复 `grok_command` 字段：去掉过时 `--keywords`，用 `--short`

#### smart_search/service.py 修复
- 修复 `httpx.HTTPStatusError` 处理时重复读取 response body 的潜在问题

#### 新增文档
- `REFACTOR_PLAN.md`：设计哲学（为什么这么改）
- `install.sh`：一键安装脚本
- `CHANGELOG.md`：本文件
- `README.md`：完整重写，包含部署指南

### 设计决策（用户拍板）

| 决策 | 结论 |
|------|------|
| 自动 fetch 所有来源 URL | ❌ 不做——替 AI 决策，浪费 5-15s |
| CLI 封装 `multi-search` 子命令 | ❌ 不做——调用 AI 自行并行即可 |
| `--verify` 自动评估 hallucination | ❌ 不做——简单正则不准，不如不做 |
| Prompt E 硬编码到 Python | ❌ 不做——prompt 应该在 SKILL.md 里 |

### 不破坏的向后兼容

- 所有原有字段保留
- 原 CLI 命令行为不变
- `_call_grok_search()` 内部实现不变

## [0.1.0] - 2026-06-27

### Initial Release

- 第一个发布版本
- 双 CLI 架构（smart-search + grok-search）
- 支持简单搜索、深度搜索、补源搜索、fetch
- 配置管理 + doctor
- 4-16 agent Grok 4.20 支持
