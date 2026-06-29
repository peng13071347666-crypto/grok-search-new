---
name: grok-search
description: 基于 Grok AI Agent 主搜索 + 多源补源的智能搜索。Grok 作为子代理执行调研任务，Brave/百度/News/Serper 作为搜索 API 补源。即使不明确说"搜索"，只要需要联网获取最新信息就触发。
---

# Grok Search

**单 CLI 架构**：`grok-search` 统一入口，内置 Grok AI Agent 主搜索 + 多源补源（Brave/百度/News/Serper/Tavily）。

**核心定位**：
- **Grok 是 AI Agent**，不是搜索 API。它有完整的任务拆解、多步规划、结构化回答能力，内部运行 4-16 个专精 Agent 并行调研、交叉验证、辩论合成。把它当作**独立调查的子代理**来用。
- **Brave/百度/News/Serper 是搜索 API**，没有综合总结能力，只给关键词让它搜索返回链接列表。
- **调用方 AI 是最终判断者（审稿人）**——Grok 输出三层调研结论（保守/平衡/激进），标注证据状态和可核验 URL。调用 AI 负责审核、取舍、最终表达。Grok 是**高级调研官**。

**核心原则**：规划归 AI，执行归 CLI。补源按档位分级，不所有 deep 都跑 3 路。

## 已配置 API Key

| 服务 | 用途 | 调用方式 |
|------|------|---------|
| Grok | AI Agent 主搜索，子代理调研 | grok-search CLI |
| Brave Search | 英文/通用搜索 + 补源 | grok-search CLI |
| 百度千帆 | 中文/国内搜索 + 补源 | grok-search CLI |
| News API | 新闻/时效补源 | grok-search CLI |
| Serper (Google) | 通用补源 | grok-search CLI |
| Tavily | Brave 失败兜底 + fetch 兜底 | grok-search CLI |

**fetch 链路**：Jina Reader（免费，无限量，返回 Markdown）→ httpx + HTML→Text → Tavily/Firecrawl（兜底）。优先 Jina。

## 模型选择

中转站模型不稳定，**不能写死模型名**。每次会话首次搜索前预检（不计费，`/models` 端点只列模型名，不走推理）：

```bash
grok-search doctor --format json
```

只取 `main_search_connection_tests.openai-compatible.models_endpoint_test.available_models`。

**按场景从列表中匹配（选第一个命中的）：**

**日常/快查/新闻/定义**：
1. 含 `fast` 且**不含** `reasoning`
2. 含 `multi-agent-console` 或 `console`
3. 列表第一个

**深度研究/调研/对比/技术细节**：
1. 含 `xhigh`
2. 含 `multi-agent-console`
3. 含 `multi-agent`
4. 日常链兜底

**排除**：含 `reasoning` 的模型不适合搜索。

---

## 搜索策略：三档决策树

### 档位 0 — Simple（不触发 Grok）

**适用**：定义、概念解释、一句话能答、已知权威来源在哪。

**流程**：
```
grok-search brave|baidu "关键词" --count 5
  → 直接调用搜索api，整理后回答。
  → 如果内容不满意，升级到档位一。

```

**补源**：不跑。

**耗时**：3-10s。

### 档位 1 — Single Agent

**适用**：单主题调研、两个选项对比、方向一致的问题。

**流程**：
```
Phase 1：AI 用 Prompt E 组织 task
  → grok-search search --deep "Prompt E" --short "关键词" --intent ... --model MODEL_NAME
    ├─ Grok 调研（内部 grok_search）
    ├─ Brave 补源（失败 → Tavily 兜底）
    └─ 意图补源
  → AI 分析 Research Verdict Package

Phase 2：AI 判断是否触发定向核实（满足任一硬触发条件）
  → 不触发 → 直接综合输出
  → 触发 ↓

Phase 3：定向核实（Prompt V，深度优先搜索 + 交叉验证）
  → grok-search search --deep "Prompt V" --short "关键词" --intent ... --model ...
  → AI 综合 Phase 1 + Phase 3 结果 → 输出
```

**硬触发条件（满足任一）**：

| 条件 | 说明 |
|------|------|
| 保守结论和平衡结论方向不一致 | 需要裁定 |
| 强判断（"最强/第一/唯一"）的证据状态不是"已打开核验" | 事实性结论必须验证 |
| 用户有时间限定（"目前""2026年"），但关键数据 > 2 周旧 | 时效性问题 |
| 任一层的可信度标为"低" | Grok 自己说不可信 |

**补源**：Phase 1 默认跑，简单任务可 `--no-supplement` 跳过。Phase 3 不跑补源。

**耗时**：Phase 1 60-90s，Phase 3 30-50s。

### 档位 2 — Multi Agent

**适用**：多对象对比（对象相互独立）、跨领域调研。一致性主题（如"国内 LLM 选型"）用档位 1 的 xhigh 即可，不需要拆。档位 2 适用于对象独立性强的任务（如分别调研 3 个不同框架的生态）。

**子任务类型**：

| type | 用途 | 依赖 |
|------|------|:--:|
| `subject` | 独立调研单个对象 | 否 |
| `comparison` | 找多个对象的差异点 | 是（依赖 subject 输出） |

**流程**：
```
Phase 1：AI 拆任务
  → subject 并行执行（Prompt E，聚焦单对象）
  → subject 全部完成后，comparison 执行（对比变体）

Phase 2：AI 判断是否触发定向核实（同档位 1 硬触发条件）
  → 不触发 → 直接综合
  → 触发 ↓

Phase 3：定向核实（Prompt V，针对矛盾点和不明确点）
  → AI 综合 Phase 1 + Phase 3 → 输出
```

**补源**：Phase 1 只在 lead agent 跑。Phase 3 不跑补源。

**耗时**：Phase 1 90-180s+，Phase 3 30-50s。

### 档位决策表

| 条件 | 档位 |
|------|:--:|
| 定义、概念解释、一句话能答 | **0** |
| 单主题、两个选项对比、方向一致 | **1** |
| 3+ 独立对象、跨领域、需要 comparison | **2** |
| 用户明确说"深度搜索/交叉验证/核验" | **1**（如对象独立则 **2**） |
| 含 ≥2 个独立可证伪的关键论点 | **1** |

---

## Grok Prompt 模板（Prompt E）

### 主模板（档位 1 single / 档位 2 subject）

```
你是 Grok 多 Agent 深度搜索调研官。使用 web_search 和 x_search。

任务：{task}

搜索要求：
- 先宽搜摸清全貌，再窄搜核验关键结论
- 关键事实打开网页验证；排名/分数/最强等强判断标注证据状态
- 不同来源冲突时列出差异，不选边
- 新名称/版本以搜索结果为准
- x_search 用于社媒舆情，web_search 用于事实核验

输出三层结论：

1. 保守结论 — 只采信已打开核验的高质量来源。标注证据状态和 URL。
2. 平衡结论 — 多源交叉后的最合理判断。标注主要不确定性。
3. 激进结论 — 基于趋势和信号的前瞻判断。必须说为什么可能错。

每层标明可信度（高/中/低）。最后附 3-8 个待核实 URL。
```

### 对比变体（档位 2 comparison）

将 task 替换为：

```
对比 {A} 和 {B}（以及 {C}...），按保守/平衡/激进三层给出差异结论。
{差异维度列表}

相同部分不需要列出。每条差异标注来源 URL 和证据状态。激进结论必须说明为什么可能错。
```

其余要求不变。

### 定向核实模板 — Prompt V（Phase 3）

在 Phase 1 调研结果存在不确定点时触发。每个条目指定要核实的问题、推荐 URL 和当前证据状态。

```
你是 Grok 深度搜索调研官。任务是对以下问题进行针对性深度搜索和交叉核实，不是广泛搜索。

待核实条目：
{条目1：要核实什么 + 推荐URL + 当前证据状态}
{条目2：...}
{条目3：...}

搜索要求：
- 每个条目进行 2-3 轮窄搜
- 打开 2-3 个相关页面，提取关键数据
- 不同来源冲突时列出差异，不选边

输出（每个条目）：
- 结论：已确认 / 部分确认 / 无法确认 / 矛盾
- 关键数据、来源 URL、证据状态、可信度
```

### {task} 填写原则

**不改写用户原话**，但根据上下文决定：

| 场景 | 对 {task} 的操作 |
|------|-----------------|
| AI 无上下文，用户话模糊 | 原样传入 Prompt E，Grok 会反问澄清，不猜测 |
| AI 有上下文，知道用户指什么 | 消歧后传入。如用户说"Pi 怎么搞"，上下文显示是 Pi Coding Agent，则 task 写"调研 Pi Coding Agent 的功能和使用" |
| AI 发现用户前提有误 | 在 task 末追加备注："注：用户问题可能基于错误前提 X，请搜原问题并标注矛盾" |

**禁止**：无上下文地猜测用户意图（如 R1 "x 是啥"→ 猜成 Pi Coding Agent，R2 "a 和 b"→ 猜成 Cursor vs Claude Code）。猜错比不改写更糟。

**时效性任务的额外约束**：对于"最新版本""当前排名""最强 XX""202X 年评测"等强时效性任务，不要在 task 中预填具体的模型名称、版本号或厂商列表——你的训练数据可能已过时。让搜索去发现当前实际存在什么。如果搜索结果返回训练数据中不存在的名称，优先采信搜索结果并用 Grok 定向核实，不要用训练数据否定它。

### 设计理由

**三层结论**：深度问题通常没有单一答案。保守给确定性，平衡给可操作判断，激进给前瞻性。三层释放 Grok 16-agent 的辩论整合能力，证据状态锁风险。

**激进结论必须说为什么可能错**：本质是推测。强制自毁权威——即使被误引为用户答案，读者也能看到风险提示。

**证据状态 > 裸 URL**：Grok citations 列表是搜索途中遇到的所有 URL，不等同都支撑结论。已打开核验 vs 摘要线索 vs 弱证据的标注，让下游 AI 知道哪些可放心用。

**Prompt V 替代 fetch**：fetch 给主 AI 抛 30KB 原始网页噪声，Prompt V 让 Grok 定向深搜 + 多源交叉 + 输出结构化结论，token 和判断成本都低一个量级。

---

## 命令参考

```bash
# 模型预检（每次会话首次搜索前，不计费）
grok-search doctor --format json

# 档位 0：搜索 API 直接搜
grok-search brave|baidu "关键词" --count 5

# 档位 0：抓取原文
grok-search fetch "https://目标URL"

# 档位 1/2 Phase 1：深度搜索（Grok调研 + Brave + 意图补源）
grok-search --format json search --deep "Prompt E" --short "关键词" --intent chinese|news|general --model MODEL_NAME --timeout 300

# Phase 3：定向核实（不跑补源，深度优先搜索 + 交叉验证）
grok-search --format json search --deep "Prompt V" --short "关键词" --intent general --model MODEL_NAME --timeout 180 --no-supplement

# 独立补源
grok-search brave|baidu|news|serper|tavily "关键词" --count 5

# 配置检查
grok-search doctor
```

## 完整执行流程

```
用户提问 → 读取本 skill → 确定档位

档位 0：搜索 API 搜关键词 → fetch 原文 → AI 回答

档位 1：
  Phase 1: Prompt E → grok-search --deep → AI 审阅三层结论
  Phase 2: 检查硬触发条件 → 不触发则直接输出
  Phase 3: 触发 → Prompt V → grok-search --deep（定向核实）→ AI 综合输出

档位 2：
  Phase 1: AI 拆 subject（并行）+ comparison（串行）
  Phase 2: 同档位 1 硬触发条件
  Phase 3: 触发 → Prompt V 定向核实 → AI 综合输出
```

**硬触发条件**：保守/平衡结论不一致 | 强判断非"已打开核验" | 时效性问题 + 数据 > 2 周 | 任一层可信度=低

## Intent 选择

| intent | API | 适合场景 |
|--------|-----|---------|
| `chinese` | 百度千帆 | 中文/国内/政策/电商/国产技术 |
| `news` | News API | 新闻/时效/刚发生的事件 |
| `general` | Serper (Google) | 英文/技术/通用搜索 |

## 输出 JSON 关键字段

| 字段 | 说明 |
|------|------|
| `content` | Phase 1: Research Verdict Package（三层结论 + 证据状态）。Phase 3: 定向核实结论。**不是最终答案**，AI 必须审核证据状态后决定最终表达 |
| `primary_sources` | Grok 调研中引用的来源 |
| `brave_sources` | Brave 补源候选 URL |
| `intent_sources` | 意图补源候选 URL |
| `extra_sources` | 合并去重后的全部补源 URL |
| `source_warning` | 补源警告（需核实后才能作为证据） |
| `supplement_skipped` | 是否跳过了补源（true 当使用 --no-supplement） |
| `content_disclaimer` | 提醒 content 是调研结果，不是最终答案 |

## 失败与降级

| 场景 | 处理 |
|------|------|
| 模型不可用 | 用同一优先级链的下一个模型重试 |
| Grok 搜索超时 | 300s 一次给够，超时重试一次 |
| Brave 失败 | 自动用 Tavily 兜底 |
| 意图补源失败 | 不影响主回答，补源部分为空 |
| 全部超时 | 降级：fetch 最相关的 1-2 个 URL |
| Grok 未输出完整三层结构 | 视为 degraded。AI 从已有数据提取保守结论，激进结论可跳过 |
| Phase 3 超时或失败 | 以 Phase 1 结果为准，标注"以下数据未经定向核实" |
| 判断幻觉 | 基于内部矛盾、关键数字无来源判断 |

## 调用 AI 最终输出指南

**采信标准是证据状态，不是层次。** 保守结论也可能错（权威过时、覆盖不全）。

| 证据状态 | 引用方式 |
|---------|---------|
| 已打开核验 | 事实引用，标注 URL |
| 来源声称 | 标注"据 XX 称，未经核实" |
| 摘要线索 | 只能作为线索，非事实 |
| 冲突数据 | 列出差异，不选边 |
| 弱证据 | 背景信息，不直接引用 |

激进结论即使证据好也要保留"可能""趋势""信号"等限定词。强判断必须说明评测口径和证据状态。

**禁止**：来源声称→已证实；激进推论→确定事实；citations 列表→证据清单。

```markdown
## 核心结论
（基于 Phase 1 结论 + Phase 3 核实，标注证据等级）

## 详细分析
（分点，区分"已验证""多数来源认为""趋势信号"）

## 信息核实
- ✓ 已通过 Grok Phase 3 定向核实：...
- ✓ 已通过原文核实：...
- ⚠ 不同来源说法矛盾：...
- ⚠ 搜索结果与训练数据矛盾：已核实，以搜索结果为准
- ⚠ 以下为激进结论，非确定事实：...
- ❌ 未触发 Phase 3 或无法核实：...

## 参考来源
- Grok Phase 1 调研：...
- Grok Phase 3 核实：...
- 补源：...
```

## 注意事项

- 中文输出给用户；代码/技术名按原语言
- **Grok 是高级调研官，输出三层结论 + 证据状态。** 调用 AI 是审稿人——采信按证据状态，不按层次
- **Grok citations 列表 ≠ 证据清单。** 每个 URL 是否支撑结论以证据状态为准
- **Phase 2 硬触发条件**：保守/平衡结论矛盾 | 强判断非"已打开核验" | 时效性数据 > 2 周 | 任一层可信度=低
- **Phase 3 的 Grok 调用替代 fetch**：除非已知确切 URL 且只需提取单个数据点，否则用 Grok 定向核实而非 fetch
- **模型不要写死**：每次会话首次 `grok-search doctor` 预检
- **时效性任务禁止在 task 中预填模型名/版本号**，让搜索去发现
- 深度搜索 timeout 默认 300s
- Phase 3 不跑补源
- 档位 2 的 comparison 等所有 subject 完成后再执行
- 档位 0 适用于"知道该搜什么不需分析"的场景
