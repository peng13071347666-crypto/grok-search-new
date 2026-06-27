---
name: grok-search
description: 基于 Grok AI Agent 主搜索 + 多源补源的智能搜索。Grok 作为子代理执行调研任务，Brave/百度/News/Serper 作为搜索 API 补源。即使不明确说"搜索"，只要需要联网获取最新信息就触发。
---

# Grok Search

**双 CLI 架构**：`smart-search`（Grok AI Agent 主搜索）+ `grok-search`（补源搜索，独立工具）。

**核心定位**：
- **Grok 是 AI Agent**，不是搜索 API。它有完整的任务拆解、多步规划、结构化回答能力，背靠 x.ai 且有 X 平台独家内容。把它当作**独立调查的子代理**来用。
- **Brave/百度/News/Serper 是搜索 API**，没有综合总结能力，只给关键词让它搜索返回链接列表。

**核心原则**：规划归 AI，执行归 CLI。补源只在 `--deep` 模式运行。

## 已配置 API Key

| 服务 | 用途 | 调用方式 |
|------|------|---------|
| Grok（smart-search） | AI Agent 主搜索，子代理调研 | smart-search CLI |
| Brave Search | 英文/通用补源 | grok-search CLI |
| 百度千帆 | 中文/国内补源 | grok-search CLI |
| News API | 新闻/时效补源 | grok-search CLI |
| Serper (Google) | 通用补源 | grok-search CLI |
| Tavily | Brave 失败兜底 + fetch | grok-search CLI |

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

## 搜索策略：三层决策

### 第一层：简单 vs 复杂

满足**任一**即走复杂路径（`--deep`）：

- 用户明确说：深度搜索/深度调研/交叉验证/详细对比/核验真假
- 含 **≥2 个可独立证伪的关键论点**
- 涉及**时效敏感信息**且需要核实
- 含对比/选型/优缺点/风险/区别等关键词
- 用户特别关注结论可靠性

**走简单路径**：定义、概念解释、背景知识、闲聊、一句话能答。

### 第二层：选命令 + 组织提示词

#### 简单查询

```bash
smart-search search "用户query" --model <日常模型> --timeout 120 --format json
```

#### 复杂查询（核心：Grok 当子代理，搜索 API 给关键词）

用户提示词拆成两部分：

**① 给 Grok 的长 prompt（子代理调研任务）**：
- Grok 是 AI Agent，有拆解问题、多步规划、结构化输出的能力
- 把用户的问题整理成**任务式指令**，让 Grok 作为独立子代理去调研
- 格式：角色定位 + 调研任务 + 分步指引 + 输出要求
- 用户只有一个调研方向 → 一个子代理任务；多个方向 → 拆成多个独立调用

**② 给搜索 API 的 `--short` 参数**：

不同搜索引擎对提示词格式的响应差异很大，实测结论：

| API | 最佳格式 | 示例 |
|-----|---------|------|
| **Brave** | 英文关键词或自然语言均可 | 实测三轮对比，两者差距极小，关键词略优 |
| **Serper (Google)** | 英文自然语言短句 | `Cursor vs GitHub Copilot 2026 differences pricing` |
| **百度** | 中文自然语言短句 | `Cursor和Copilot 2026年功能差异和定价对比` |
| **News API** | 英文关键词 | 仅适合真正有时效性的新闻事件，不适合对比/调研 |

> Google 和百度早已不是纯关键词匹配引擎，自然语言短句意图理解更好。Brave 关键词和自然语言差距极小，两种都可用。

```bash
grok-search search --deep "给Grok的调研任务" --short "按上表格式的关键词或短句" --intent chinese|news|general --model <深度模型> --timeout 180 --format json
```

**给 Grok 的 prompt 格式**：

Grok 是 AI Agent。给它**角色 + 任务 + 一条来源规则**，不给任何格式约束。让它自主决定研究方法、搜索策略和输出结构。

**16 次实测结论**（5 种模式 × 多任务，同模型）：
| 模式 | 均字 | 均源 | 社区率 | X率 | 得分 |
|------|:--:|:--:|:--:|:--:|:--:|
| 纯搜索（固定格式） | 3,825 | 11 | 33% | 0% | 15.5 |
| 重混合（6 章节） | 4,652 | 10 | 100% | 67% | 22.0 |
| 轻混合（3 章节） | 5,195 | 11 | 100% | 0% | 21.9 |
| 纯代理（无格式） | 5,278 | 18 | 67% | 67% | 24.4 |
| **最终模板（无格式+来源规则）** | **6,024** | **19.5** | **100%** | **75%** | **30.8** |

**核心发现**：任何格式约束都会抑制 Grok 的研究广度。但"每个事实性断言标注来源 URL"不是格式约束，而是**研究纪律**——它让 Grok 每写一个论点就去找来源，而不是写完再回想。这条规则让来源数 +30%，社区率 50%→100%。

**最终模板**（4 句话，不可增减）：

```
你是资深[领域]分析师，可自主使用 web_search、X/Twitter 搜索等工具进行独立调研。

你的任务是：[具体调研主题]。

请自主决定研究方法、搜索策略和分析框架。利用你的工具获取多角度信息——包括官方文档、独立评测、以及 X 上开发者的真实使用反馈。每个事实性断言标注来源 URL。

请用中文输出。
```

**关键原则**：
- 不给任何输出格式约束——让 Grok 自己决定怎么组织内容，研究广度优先
- 必须要求"标注来源 URL"——驱动 Grok 深度搜索，而非事后回忆
- 提到 X/Twitter 提醒 Grok 使用这个独家数据源
- 角色 + 任务 + 一条来源规则 + 输出语言，仅此而已
- 来源分层（官方/评测/社区）留给调用 AI 在拿到结果后自己做，不要让 Grok 做

### 第三层：要不要 fetch 证据

`fetch_before_claim` 原则——**高风险声明的最终结论必须由抓取到的原文支撑**。

fetch 通过 CLI 命令执行，AI 直接调用，无需单独处理：
```bash
grok-search fetch "https://关键URL"
```

- 高风险（新闻/政策/金融/价格/版本号）→ `grok-search fetch` 关键 URL
- 低风险（定义、概念解释）→ 直接用 Grok 回答
- 典型深度研究 fetch 1–3 个 URL

## 命令参考

```bash
# 模型预检（每次会话首次搜索前，不计费）
smart-search doctor --format json

# 简单搜索（透传 smart-search）
smart-search search "query" --model <模型> --timeout 120 --format json

# 深度搜索（三路并行：Grok子代理 + Brave + 意图补源）
grok-search --format json search --deep "给Grok的调研任务" --short "关键词" --intent chinese|news|general --model <深度模型> --timeout 180

# 独立补源
grok-search brave|baidu|news|serper|tavily "关键词" --count 5

# 网页抓取核实
grok-search fetch "https://目标URL"

# 质检参考（离线零成本）
grok-search deep "问题"

# 配置检查
grok-search doctor
```

## 完整执行流程

```
用户提问
  → AI 判断是否需要搜索
    → 读取本 skill，规划两类提示词：
       ① 给 Grok 的：子代理调研任务（角色 + 任务 + 分步指引 + 输出要求）
       ② 给搜索 API 的：自然语言短句，按引擎选格式
       ③ 判断 intent：chinese / news / general
    → 注入 CLI，三路并行执行：
       grok-search search --deep "①" --short "②" --intent ③ --model <深度模型>
         ├─ Grok 子代理调研（smart-search 透传）
         ├─ Brave 补源（失败 → Tavily 兜底）
         └─ 意图补源（百度/News/Serper 按 intent 选一）
    → JSON 结果返回给 AI
      → AI 分析：content 是否充分？关键论点有无来源？
        → 需要核实 → grok-search fetch 关键 URL
        → 不需要 → 直接用
      → AI 输出最终答案（结构化报告）
```

## 深度搜索工作流

### 第 1 步：AI 规划提示词

**① 给 Grok 的子代理调研任务**（Grok 是 AI Agent，不是搜索 API）：
- 角色定位：`你是一个专业的XXX`
- 调研任务：`现在需要你调研XXX`
- 分步指引：`1. 查找... 2. 搜索... 3. 对比...`
- 输出要求：`中文输出，标注来源URL`

**② 给搜索 API 的 `--short`**（不同引擎格式不同，实测结论）：

| 引擎 | 格式 | 示例 |
|------|------|------|
| Brave | 英文关键词 5-8 词 | `Cursor Copilot AI coding assistant 2026 comparison` |
| Serper | 英文自然语言短句 | `Cursor vs GitHub Copilot 2026 differences pricing` |
| 百度 | 中文自然语言短句 | `Cursor和Copilot 2026年功能差异和定价对比` |
| News API | 英文关键词 | 仅适合真正新闻事件，不适合对比/调研 |

> ⚠️ **不要给搜索 API 子代理格式**（如"你是一个专业的..."）。实测会把中文指令词当搜索词，污染英文引擎结果，Brave/Serper 全变成中文源。

**③ 判断 intent**：中文→`chinese`，新闻→`news`，其他→`general`。

### 第 2 步：注入 CLI，三路并行执行

```bash
grok-search --format json search --deep \
  "给Grok的调研任务" \
  --short "给搜索API的自然语言短句" \
  --intent chinese|news|general \
  --model <深度模型> \
  --timeout 180
```

### 第 3 步：AI 分析结果，决定是否 fetch

拿到 JSON 后 AI 判断：
- `content` 充分 + 关键论点有来源 → 直接用，进入第 4 步
- 关键论点缺乏来源/需要核实 → `grok-search fetch "关键URL"` 取原文
- 典型深度研究 fetch 1–3 个 URL

### 第 4 步：AI 输出结构化答案

```markdown
## 核心结论
（中文总结）

## 详细分析
（分点展开，每个关键论点标注信息来源）

## 信息核实
- ✓ 已通过原文核实：...
- ⚠ 存在差异需注意：...
- ❌ 无法核实：...

## 参考来源
- Grok 来源：...
- Brave 补源：...
- 百度/News/Serper 补源：...
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
| `content` | Grok 子代理的回答正文，**直接作为最终回答主体** |
| `primary_sources` | Grok 引用的来源 |
| `brave_sources` | Brave 补源候选 URL |
| `intent_sources` | 意图补源候选 URL |
| `extra_sources` | 合并去重后的全部补源 URL |
| `source_warning` | 补源警告（fetch 核实后才能作为证据） |

## 失败处理

| 场景 | 处理 |
|------|------|
| 模型不可用（model_not_found/503） | 用同一优先级链的下一个模型重试 |
| Grok 主搜索超时 | 日常 120s、深度 180s 一次给够，超时重试一次 |
| Brave 失败 | 自动用 Tavily 兜底（内置） |
| 意图补源失败 | 不影响 Grok 回答，补源部分为空 |
| 全部超时 | 降级：`grok-search fetch` 最相关的 1–2 个 URL |
| 判断幻觉 | 基于搜索结果内部矛盾、关键数字无来源判断 |

## 注意事项

- 给用户看的解释用中文；交付物按它本身该用的语言
- **补源结果不是证据**，作为论据必须先 `grok-search fetch` 核实
- 补源只在 `--deep` 模式运行，简单查询不加 `--deep`
- 拆了子任务后，每个子任务单独走一次深度流程
- **模型不要写死**：每次会话首次搜索前跑 `smart-search doctor` 预检，按优先级链选
- **Grok 是子代理，不是搜索 API**：给它调研任务，给它分步指引，让它产出结构化回答