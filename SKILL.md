---
name: grok-search
description: 基于 Grok AI Agent 主搜索 + 多源补源的智能搜索。Grok 作为子代理执行调研任务，Brave/百度/News/Serper 作为搜索 API 补源。即使不明确说"搜索"，只要需要联网获取最新信息就触发。
---

# Grok Search

**双 CLI 架构**：`smart-search`（Grok AI Agent 主搜索）+ `grok-search`（补源搜索，独立工具）。

**核心定位**：
- **Grok 是 AI Agent**，不是搜索 API。它有完整的任务拆解、多步规划、结构化回答能力，背靠 x.ai 且有 X 平台独家内容，内部运行 4-16 个专精 Agent 并行调研、交叉验证、辩论合成。把它当作**独立调查的子代理**来用。
- **Brave/百度/News/Serper 是搜索 API**，没有综合总结能力，只给关键词让它搜索返回链接列表。
- **调用方 AI 是最终判断者**——拿到 Grok 的调研原料和补源结果后，自己验证、综合、得出结论。Grok 的输出是**原料，不是答案**。

**核心原则**：规划归 AI，执行归 CLI。补源按档位分级，不所有 deep 都跑 3 路。

## 已配置 API Key

| 服务 | 用途 | 调用方式 |
|------|------|---------|
| Grok（smart-search） | AI Agent 主搜索，子代理调研 | smart-search CLI |
| Brave Search | 英文/通用搜索 + 补源 | grok-search CLI |
| 百度千帆 | 中文/国内搜索 + 补源 | grok-search CLI |
| News API | 新闻/时效补源 | grok-search CLI |
| Serper (Google) | 通用补源 | grok-search CLI |
| Tavily | Brave 失败兜底 + fetch 第三级兜底 | grok-search CLI |

**fetch 链路**：Jina Reader（免费, 无限量, 返回干净 Markdown）→ 直接 httpx + HTML→Text → Tavily/Firecrawl（兜底）。主力是 Jina，不消耗 Tavily 配额。

## 模型选择

中转站模型不稳定，**不能写死模型名**。每次会话首次搜索前预检（不计费，`/models` 端点只列模型名，不走推理）：

```bash
smart-search doctor --format json
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

按任务复杂度分为 3 档，不是 binary 的"简单 vs 复杂"：

### 档位 0 — Simple（不触发 Grok）

**适用**：定义、概念解释、一句话能答、已知权威来源在哪。

**流程**：
```
grok-search brave|baidu "关键词" --count 5
  → 从搜索结果中选 1-2 个最相关 URL
  → grok-search fetch "URL"
  → 调用 AI 用 fetch 到的原文直接回答
```

**不走 Grok 的原因**：简单问题不需要多 Agent 辩论和深度调研，直接 fetch 原文比 Grok 转述更可靠。

**补源**：不跑。

**耗时**：3-10s。

### 档位 1 — Single Agent（1 个 Grok 调用）

**适用**：单主题调研、对比两个选项、需要多角度但方向一致的问题。

**流程**：
```
调用 AI 用 Prompt E 组织 task
  → grok-search search --deep "Prompt E" --short "关键词" --intent ... --model <深度模型>
    ├─ Grok 子代理调研（smart-search 透传）
    ├─ Brave 补源（失败 → Tavily 兜底）
    └─ 意图补源（按 intent 选一）
  → 调用 AI 分析 content + extra_sources
    → 需要核实 → grok-search fetch 关键 URL
    → 输出最终答案
```

**补源**：默认跑。简单 deep 任务可加 `--no-supplement` 跳过。

**耗时**：50-80s。

### 档位 2 — Multi Agent（N 个 Grok 并行调用）

**适用**：多对象对比（对象相互独立）、跨领域调研、5+ 对象需要覆盖。

**判断标准**：对象/方向是否**独立可分**。一致性主题（如"国内 LLM 选型"）用档位 1 的 xhigh（16 Agent 内部已并行）就够了，不需要拆。真正需要档位 2 的是"对象独立性强"的任务（如分别调研 3 个不同框架的生态）。

**两种子任务类型**：

| type | 用途 | 依赖 |
|------|------|:--:|
| `subject` | 独立调研单个对象 | 否 |
| `comparison` | 找多个对象的差异点 | 是（依赖 subject 输出） |

**为什么需要 comparison**：两个 subject 各自调研 A 和 B，都"对另一方毫无所知"。只有 comparison 才能找到真正的差异点。没有 comparison，调用方拿到的只是"A 的描述"+"B 的描述"，没有"差异表"。

**流程**：
```
调用 AI 拆任务：
  → subject 任务并行执行（每个用 Prompt E，task 聚焦单个对象）
  → 所有 subject 完成后，comparison 任务执行（用 Prompt E 差异变体）
  → 每个任务独立收结果，调用 AI 综合
```

**补源**：只在 lead agent 跑，subagent 用内置 web_search。

**耗时**：90-180s+。

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
你是信息收集专家，运行在多 Agent 协作模式下。你可使用 web_search 和 x_search 工具从多角度全面收集信息。

你的任务是：{task}

【研究纪律】
1. Start wide, then narrow：先用 2-3 个宽泛 query 摸清信息全貌，再针对关键缺口用具体 query 深入。
2. 不要重复搜索同一关键词——如果前一轮搜索已覆盖某角度，换方向。
3. 充分利用 x_search 获取 X/Twitter 上的独家用户反馈和社区讨论。
4. 来源优先级：官方文档/公告 > 独立 benchmark 评测 > 开发者社区反馈 > 营销博客。

【输出规则】
- 每个信息点必须标注来源 URL。
- 不同信息源对同一问题的不同说法都要如实收录，不要选边、不要调和。
- 不需要写结论、推荐或主观评价——这些留给后续分析。
- 如果某个方向搜索不到相关内容，标注"[未找到相关搜索结果]"。
- 如果用户的问题模糊、缺少具体对象或时间/场景约束，先反问 1-2 个澄清问题，不要猜测。
- 用中文输出，篇幅根据信息量自然决定。
```

### 差异变体（档位 2 comparison）

将 task 替换为：

```
对比 {A} 和 {B}（以及 {C}...）在以下维度的差异：
{差异维度列表}

只收集两者的不同点。相同的部分不需要列出。每条差异标注来源 URL。
```

其余【研究纪律】和【输出规则】不变。

### {task} 填写原则

**不改写用户原话**，但根据上下文决定：

| 场景 | 对 {task} 的操作 |
|------|-----------------|
| AI 无上下文，用户话模糊 | 原样传入。壳的"反问引导"会接管 |
| AI 有上下文，知道用户指什么 | 消歧后传入。如用户说"Pi 怎么搞"，上下文显示是 Pi Coding Agent，则 task 写"调研 Pi Coding Agent 的功能和使用" |
| AI 发现用户前提有误 | 在 task 末追加"注：用户问题可能基于错误前提 X，请搜原问题并在发现矛盾时标注" |

**禁止**：无上下文地猜测用户意图（如 R1 "x 是啥"→ 猜成 Pi Coding Agent，R2 "a 和 b"→ 猜成 Cursor vs Claude Code）。猜错比不改写更糟。

### 设计理由

**为什么要禁止结论和推荐**：Grok 可能给出看起来完整但核心答案错误的内容（如把"Pi"误解为 Pi Network 加密货币，给出 1877 字自信但全错的回答）。结论和推荐留给调用 AI 自己判断。

**为什么要收录不同说法**：经 9 次对比测试（3 难度 × 3 种 prompt），显式标注"不同说法"的版本让调用 AI 知道哪里需要核实。禁止分析但保留矛盾发现是最佳平衡点。

**为什么要反问引导**：不改写用户原话意味着模糊输入会被原样传入。壳必须教会 Grok 面对模糊问题时的正确行为——反问，不猜测。

**为什么说"多 Agent 协作模式"**：Grok 4.20 内部有 4-16 个专精 Agent，提示"多 Agent 协作"能激活其内部并行调研和交叉验证，但不确定死角色（xAI 从未官方公布 16 Agent 的名称和职责清单，社区推断可能不准确）。

---

## 搜索 API 的 --short 参数格式

不同搜索引擎对提示词格式的响应差异很大：

| API | 最佳格式 | 示例 |
|-----|---------|------|
| **Brave** | 英文关键词或自然语言均可 | 实测差距极小，关键词略优 |
| **Serper (Google)** | 英文自然语言短句 | `React state management Zustand Jotai Redux 2026 comparison` |
| **百度** | 中文自然语言短句 | `React状态管理Zustand和Jotai 2026年对比` |
| **News API** | 英文关键词 | 仅适合真正有时效性的新闻事件 |

> ⚠️ **不要给搜索 API 子代理格式**（如"你是一个专业的..."）。实测会把中文指令词当搜索词，污染英文引擎结果，Brave/Serper 全变成中文源。

---

## 命令参考

```bash
# 模型预检（每次会话首次搜索前，不计费）
smart-search doctor --format json

# 档位 0：搜索 API 直接搜
grok-search brave|baidu "关键词" --count 5

# 档位 0：抓取原文
grok-search fetch "https://目标URL"

# 档位 1/2：深度搜索（三路并行：Grok子代理 + Brave + 意图补源）
grok-search --format json search --deep "Grok调研任务" --short "关键词" --intent chinese|news|general --model <深度模型> --timeout 180

# 档位 1 跳过补源（简单 deep 任务）
grok-search --format json search --deep "任务" --short "关键词" --intent general --model <模型> --timeout 180 --no-supplement

# 独立补源
grok-search brave|baidu|news|serper|tavily "关键词" --count 5

# 配置检查
grok-search doctor
```

## 完整执行流程

```
用户提问
  → AI 判断是否需要搜索
    → 读取本 skill，确定档位（0 / 1 / 2）

  ┌─ 档位 0 ───────────────────────────────────────┐
  │ grok-search brave|baidu "关键词"                │
  │   → 选 1-2 个最相关 URL                         │
  │   → grok-search fetch "URL"                     │
  │   → AI 用原文直接回答                            │
  └────────────────────────────────────────────────┘

  ┌─ 档位 1 ───────────────────────────────────────┐
  │ AI 用 Prompt E 组织 task                         │
  │   → 组织 --short 关键词（按引擎选格式）            │
  │   → 判断 intent：chinese / news / general        │
  │   → grok-search search --deep "task"             │
  │       --short "关键词" --intent ... --model ...   │
  │     ├─ Grok 子代理调研                           │
  │     ├─ Brave 补源（可选跳过）                     │
  │     └─ 意图补源                                  │
  │   → AI 分析 content + sources                    │
  │     → 需要核实 → grok-search fetch 关键 URL      │
  │     → AI 综合输出最终答案                         │
  └────────────────────────────────────────────────┘

  ┌─ 档位 2 ───────────────────────────────────────┐
  │ AI 拆任务为 subject + comparison                  │
  │   → subject 并行（每个用 Prompt E）               │
  │   → comparison 串行（用差异变体）                  │
  │   → 每份结果独立返回，AI 综合                      │
  │   → 需要核实时 fetch                              │
  └────────────────────────────────────────────────┘
```

## Intent 选择

| intent | API | 适合场景 |
|--------|-----|---------|
| `chinese` | 百度千帆 | 中文/国内/政策/电商/国产技术 |
| `news` | News API | 新闻/时效/刚发生的事件 |
| `general` | Serper (Google) | 英文/技术/通用搜索 |

## 输出 JSON 关键字段

| 字段 | 说明 |
|------|------|
| `content` | Grok 子代理的调研结果（**原料，不是最终答案**。调用 AI 必须自己验证和判断） |
| `primary_sources` | Grok 调研中引用的来源 |
| `brave_sources` | Brave 补源候选 URL |
| `intent_sources` | 意图补源候选 URL |
| `extra_sources` | 合并去重后的全部补源 URL |
| `source_warning` | 补源警告（fetch 核实后才能作为证据） |
| `supplement_skipped` | 是否跳过了补源（true 当使用 --no-supplement） |
| `content_disclaimer` | 提醒 content 是原料而非最终答案 |

## 失败处理

| 场景 | 处理 |
|------|------|
| 模型不可用（model_not_found/503） | 用同一优先级链的下一个模型重试 |
| Grok 主搜索超时 | 日常 120s、深度 180s 一次给够，超时重试一次 |
| Brave 失败 | 自动用 Tavily 兜底（内置） |
| 意图补源失败 | 不影响 Grok 回答，补源部分为空 |
| 全部超时 | 降级：`grok-search fetch` 最相关的 1–2 个 URL |
| 判断幻觉 | 基于搜索结果内部矛盾、关键数字无来源判断 |

## AI 最终回答模板

```markdown
## 核心结论
（调用 AI 基于 Grok 原料 + fetch 核实后的综合判断）

## 详细分析
（分点展开，关键论点标注信息来源和核实状态）

## 信息核实
- ✓ 已通过原文核实：...
- ⚠ 不同来源说法矛盾，需注意：...
- ❌ 无法核实（来源缺失/标记为"[未找到相关搜索结果]"）：...

## 参考来源
- Grok 调研来源：...
- 补源：...
- 独立 fetch 核实：...
```

## 注意事项

- 给用户看的解释用中文；交付物按它本身该用的语言
- **Grok 的 content 是原料，不是答案**。调用 AI 必须自己验证关键论断、发现矛盾、做出判断
- **补源结果不是证据**，作为论据必须先 `grok-search fetch` 核实
- 拆了子任务后，每个子任务单独走一次深度流程
- **模型不要写死**：每次会话首次搜索前跑 `smart-search doctor` 预检，按优先级链选
- **不要自动改写用户原话**：有上下文时消歧，无上下文时原样传入 + 靠 Prompt E 的反问引导兜底
- 档位 2 的 comparison 必须等所有 subject 完成后再执行
- 档位 0 适用于"知道该搜什么但不需要分析"的场景，不是"偷懒不上 Grok"
