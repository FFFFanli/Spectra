# Spectra 统一 Agent 重构规划

> 起草时间：2026-05-21
> 目标产品参考：Trae Solo / Cursor Composer / Claude Code
> 核心结论：**砍掉 Solo / Team 模式选择，收敛为单一 Supervisor Agent + 丰富工具 + 长程规划循环**

---

## 一、问题诊断

### 1. 现状痛点

| 现象 | 根因 |
|---|---|
| 用户分不清何时该选 Solo 还是 Team，"自动模式"边界 case 多 | 架构上是两个完全独立的大脑（Solo 不知 Coder 存在；Team 不知 web_search 存在） |
| Researcher 与 Solo 的搜索能力重叠 | Team 的"成员"本质是 prompt + validator 配置，与 Solo 工具同源 |
| Team 模式跑 5 步以上的复杂任务必失败 | Supervisor 每轮只看 task_goal + schema，没有 plan / 进度 / 历史产物上下文，且 max_rounds=8 硬上限 |
| Supervisor 频繁把 tool_call 写成文字 | prompt 是静态决策树（"出现 X → assign Y"），不是规划 |
| 多 Agent 调度成本高于专业化收益 | Coder/Writer/Researcher 三个角色实质是三组 prompt，没有 token 维度上必须分头的强场景 |

### 2. 架构判断

对标产品（Trae Solo / Cursor Composer / Claude Code）**没有一个是多 Agent 架构**。
它们的共同模式是：

```
单 Agent + 丰富工具 + 长程规划循环 + 实时 Plan/Todo 状态
```

Spectra 当前 Team 模式做了两次 LLM 调用、走两套 prompt、分两次上下文，
最终成果与"一个聪明 Agent 调一次工具"没有本质差别，反而牺牲了：
- 上下文连贯性（成员之间靠 prompt 拼接传递，而非共享对话）
- 决策可解释性（Supervisor 路由是黑盒，用户看不到为什么派给某成员）
- 端到端速度（每轮多一次 LLM 调用）

### 3. 真正有价值的资产

v2 实现里**值得保留的部分**：

| 资产 | 位置 | 保留原因 |
|---|---|---|
| executor → validator → fixer 自检循环 | `backend/agent/v2/infra/executor_impl.py` | 一年踩坑攒出来的产物校验逻辑（PDF 含图、xlsx 必导出、错误自动修复）|
| LLM 工厂 | `backend/agent/v2/llm.py` | DashScope/OpenAI/DeepSeek 三 provider 统一入口 |
| Skill Registry（待评估） | `backend/skill_registry.py` | 见 §五 决策点 1 |
| E2B + 本地子进程双引擎 | `backend/agent/v2/infra/executor_impl.py` | 沙盒执行的关键基础设施 |

**该砍的部分**：

| 该砍 | 原因 |
|---|---|
| `backend/agent/v2/runtime.py`（编排循环） | 多 Agent 路由层，是负担 |
| `backend/agent/v2/planner.py`（状态机） | 服务于多 Agent 路由，单 Agent 不需要 |
| `backend/agent/v2/prompts/supervisor.py` | 路由型 prompt 整套作废 |
| `backend/agent/v2/members/{coder,writer,researcher,responder}.py` | 角色概念消失，但内部代码作为"工具实现"被吸收 |
| `backend/agent/v2/tools.py`（assign / broadcast / 等）| 多 Agent 编排工具全部作废 |
| `backend/agent/v2/state.py` 的 TeamState | 用单 Agent 的 PlanState 替代 |
| 前端 Solo / Team / 自动 三个按钮 | 用户看不到模式切换 |
| `pickAgentMode` 启发式路由 | 不再需要 |

---

## 二、目标体验

跑通后用户看到的是：

```
┌─────────────────────────────────────────────────────────────┐
│  💬 用户：基于 orders 表写一份 2025 年销售分析 PDF 报告       │
└─────────────────────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────────────────────┐
│  📋 Plan（实时显示在右侧抽屉，agent 自己制定）                │
│  ✓ 1. 探索 orders 表结构                                     │
│  ⟳ 2. 按月聚合销售额，识别趋势                                │
│  ○ 3. 生成 plotly 折线图（HTML + PNG）                       │
│  ○ 4. 撰写 PDF 报告，嵌入图表                                 │
│  ○ 5. 校验产物，输出最终下载链接                              │
└─────────────────────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────────────────────┐
│  🔧 工具调用流（实时，与 Plan 联动）                           │
│  list_tables() → orders, products, ...                       │
│  read_table_schema(orders) → ...                             │
│  query_duckdb("SELECT ...") → ...                            │
│  run_in_sandbox(<plotly code>) → chart.html, chart.png       │
│  generate_pdf_report({...}) → report.pdf                     │
└─────────────────────────────────────────────────────────────┘
   ↓
┌─────────────────────────────────────────────────────────────┐
│  📎 产物：report.pdf, chart.html, chart.png                   │
│  💡 总结：完成。报告包含 5 个章节…                             │
└─────────────────────────────────────────────────────────────┘
```

前端聊天框只剩**模型选择 + 输入框**，没有任何模式选择。

---

## 三、统一工具面板（取代多成员）

### 3.1 当前 Solo 已有的轻量工具（保留）

| 工具 | 实现位置 | 说明 |
|---|---|---|
| `web_search` | `backend/tools/web_search.py` | DuckDuckGo 搜索 |
| `crawl_page` | `backend/tools/web_search.py` | Jina AI 抓页 |
| `search_and_crawl_tool` | `backend/tools/web_search.py` | 搜索+抓取一体 |
| `calculator` | `backend/tools/calculator.py` | 安全数学表达式 |
| `summarize_numbers` | `backend/tools/calculator.py` | 描述性统计 |
| `generate_chart` | `backend/tools/visualization.py` | Plotly 代码生成 |
| `execute_python` | `backend/tools/sandbox.py` | E2B 远程执行 |

### 3.2 新增的"重型工具"（吸收原 Team 成员能力）

| 工具 | 替代原成员 | 内部实现 |
|---|---|---|
| `run_in_sandbox(code, expect_artifacts)` | Coder | 包装 v2 的 executor → validator → fixer 循环；`expect_artifacts` 指定校验配置（chart/xlsx/none）|
| `generate_pdf_report(spec)` | Writer (PDF) | LLM 写 reportlab 代码 → 沙盒跑 → 校验必含图 |
| `generate_docx_report(spec)` | Writer (DOCX) | LLM 写 python-docx 代码 → 沙盒跑 → 校验产物 |
| `search_to_db(query, table_name, max_results)` | Researcher | 复用 search_service 预取 + 强制入 DuckDB；返回入库行数 |
| `list_tables()` | （DuckDB schema 探索） | 列出当前所有用户表 |
| `read_table_schema(table)` | （DuckDB schema 探索） | 返回单表列定义与样例行 |
| `query_duckdb(sql)` | （DuckDB 直接读）| 让 Agent 看自己产物，不必每次都进沙盒 |

### 3.3 规划工具（核心）

| 工具 | 说明 |
|---|---|
| `make_plan(steps: list[str])` | **强制首次调用**。把 task 拆成 TODO 列表，写入 PlanState |
| `update_plan(step_id, status, note)` | 标记某步状态（pending / running / done / failed）|
| `add_step(after_step_id, description)` | 发现新需求时插入 |
| `revise_plan(reason, new_steps)` | 失败 ≥3 次或路线明显错误时整体重排 |
| `finish(summary)` | 显式收尾，输出最终回复 |

---

## 四、状态设计：PlanState

替换原 TeamState。**单 Agent 共享同一份 messages，不再有"成员独立上下文"**。

```python
class PlanState(TypedDict, total=False):
    # 对话
    messages: Annotated[list, add_messages]
    task_goal: str

    # 规划
    plan: list[PlanStep]            # [{id, description, status, note, started_at, finished_at}]
    plan_revision: int              # 重排次数（防止无限 revise_plan）

    # 工具调用
    tool_call_count: int
    last_tool_name: str

    # 预算
    max_steps: int                  # 默认 50
    max_tokens: int                 # 默认 50_000，触发自动压缩
    consumed_tokens: int

    # 产物（向后兼容旧 SSE 协议）
    artifacts: list[dict]
    chart_paths: list[str]
    report_paths: list[str]
    cleaned_file_paths: list[str]

    # 终止
    finished: bool
    finish_reason: str              # "completed" / "max_steps" / "max_tokens" / "user_stopped" / "max_revisions"
```

---

## 五、决策点（实施前需要拍板）

### 决策 1：Skill Registry 去留

**选项 A · 保留**：`generate_pdf_report` / `generate_docx_report` 内部继续接 skill 匹配，沿用 `.trae/skills/*/SKILL.md`
**选项 B · 删除**：让 LLM 现写 reportlab/python-docx 代码，删除整个 skill_registry 子系统（约 300 行）

> 倾向：**B**。当前 skill 内容很薄，更像示例 prompt 片段，距离"动态创建/复用 skill"愿景太远。删了之后 Writer 类工具变成干净的"调 LLM → 沙盒 → 校验"。
>
> 待你拍板。

### 决策 2：HITL 代码确认是否回归

v1 有 `/api/chat_resume`，让用户在沙盒执行前审核代码。v2 已删除。

**选项 A · 不要**：完全自动，所有代码进沙盒（当前状态）
**选项 B · 可选 HITL**：在前端加一个"代码执行前请求确认"开关，默认关

> 倾向：**B**。沙盒虽然安全，但生产场景下用户对"动了哪张表"心里有数比无脑跑更舒服。
>
> 待你拍板。

### 决策 3：附件透传修复时机

> 当前 bug：前端切到 supervisor 路径时不会把 `attachedFiles / db_alias` 传给后端。
> 切到统一 Agent 后这个问题等价于"前端 attachedFiles 不传给后端"，仍然需要修。

**选项 A · Phase 1 内修**：第一阶段就一并处理，免得统一后立刻遇到这个坑
**选项 B · Phase 0**：先于 Phase 1 单独修一版上线，独立验证

> 倾向：**A**。只是几行 streamFetch body 增量。

---

## 六、分阶段实施

### Phase 0 · 准备（0.5 天）

| 任务 | 状态 |
|---|---|
| 本规划文档评审 + 决策点拍板 | ⏳ 待你回复 |
| 起一个干净分支：`unified-agent` | ⏳ |
| 列出所有 v2 待删 / 待移文件清单（已在 §一.3 列出，开发时按清单走）| ✅ |

---

### Phase 1 · 收敛入口（2-3 天）

> **目标**：用户层面消失模式选择，后端只剩一个 Agent；旧能力以"工具"形式接入。

#### 1.1 后端

- [ ] 在 `backend/agent/single_agent.py` 增加 PlanState 字段（保留向后兼容）
- [ ] 新增 `backend/agent/tools_heavy.py`：
  - [ ] `run_in_sandbox(code, expect_artifacts)` 内部调 v2 `executor_node + validator_node + fixer_node`
  - [ ] `generate_pdf_report(spec)` 内部调 v2 WriterMember 的 PDF 路径
  - [ ] `generate_docx_report(spec)` 内部调 v2 WriterMember 的 DOCX 路径
  - [ ] `search_to_db(query, table_name, max_results)` 内部调 search_service + DuckDB 入库
  - [ ] `list_tables()` / `read_table_schema(table)` / `query_duckdb(sql)` 直接复用 db_utils
- [ ] 把 single_agent 的 `max_steps` 从 15 调到 40
- [ ] `backend/agent/single_agent.py` 的 SystemPrompt 改写：
  - 删掉前端拼接的 SINGLE_AGENT_BASE_PROMPT（搬到后端）
  - 引入"何时该用重型工具"的指引
- [ ] `backend/api.py` 的 `/api/chat`（Team 端点）改为转发到 single_agent 实现，**保留 URL** 以兼容前端
- [ ] 删除 `backend/agent/v2/{runtime,planner,tools,prompts/supervisor}.py`
- [ ] 删除 `backend/agent/v2/members/{coder,writer,researcher,responder}.py`
- [ ] `backend/agent/v2/state.py` 改名 `backend/agent/plan_state.py` 并瘦身为 PlanState
- [ ] `backend/agent/v2/infra/*` 保留，作为新工具的内部实现
- [ ] 修复附件透传 bug（决策 3 拍板后）

#### 1.2 前端

- [ ] `ChatView.vue` 删除 mode-selector 组件（Solo / Team / 自动 三个按钮）
- [ ] `useChat.js` 删除 `pickAgentMode` 函数与所有 mode 分支
- [ ] `useChat.js` 把 `streamSingleAgent / streamChatParsed` 合并为单一 `streamAgent`，固定打 `/api/chat`
- [ ] 删除 store 里的 `agentMode / agentModeAdvanced / agentModeLastUsed` 字段
- [ ] 删除前端硬编码的 `SINGLE_AGENT_BASE_PROMPT`（搬到后端后前端不再持有）
- [ ] 前端调用时把 `attachedFiles / dbConfig` 一并传给 `/api/chat`

#### 1.3 验收

- [ ] "你好" → 直接答（不调任何工具）
- [ ] "搜一下 Anthropic 最近发布" → 调 web_search → 文字摘要
- [ ] "统计 sales 表各品类销售总额" → list_tables → query_duckdb → 出结论
- [ ] "看下 orders 月度趋势" → query_duckdb → run_in_sandbox 出图
- [ ] "基于 orders 写 PDF 销售分析报告" → 多步：先出图 → generate_pdf_report → 产物下载
- [ ] "调研 Anthropic 入库" → search_to_db → 检查 DuckDB search_results 表

#### 1.4 Phase 1 完成定义（DoD）

- 用户聊天界面无任何模式切换
- 后端只有一个 agent 实现
- 上述 6 个验收用例全部通过
- v2 待删文件全部消失，v2/infra 保留作为工具内部实现

---

### Phase 2 · 长程规划循环（3-5 天）

> **目标**：达到 Trae Solo 体感 —— 用户能看到实时 Plan / Todo / 进度，长任务能自我修复。

#### 2.1 后端

- [ ] 实现 `make_plan / update_plan / add_step / revise_plan / finish` 五个规划工具
- [ ] System prompt 强制首步调 `make_plan`：
  - 进 LLM 第一轮如果没调用 `make_plan`，强制重发指令
  - 一旦调用过，后续每一步可以选择是否更新
- [ ] PlanState 引入 token 预算追踪（`consumed_tokens` 累计 LLM usage）
- [ ] 接近预算时自动调 `compact_history` 工具：把已完成的工具调用结果压缩成"阶段性摘要"
- [ ] 失败 ≥3 次（fixer 仍未通过）触发 `revise_plan`
- [ ] SSE 协议新增事件：
  - `plan_created` `plan_updated` `plan_revised` `step_started` `step_completed` `step_failed`
  - `budget_warning`（接近 token 上限时）
  - `compact_history`（自动压缩发生时）

#### 2.2 前端

- [ ] 右侧抽屉新增"任务规划"模块：
  - Plan 实时渲染为 checklist
  - 当前步骤高亮 + 进度条
  - 失败步骤红色标记 + 错误摘要
- [ ] 工具调用区与 Plan 联动：每次 tool_call 显示"属于哪一步"
- [ ] 顶部显示预算条（已用 / 剩余 tokens 与 steps）

#### 2.3 验收

- [ ] 5 步以上的复杂任务（如"调研 + 数据分析 + 出 PDF 报告"）能跑完
- [ ] 中途某步失败 → fixer 修 → 仍失败 3 次 → revise_plan 自动改路线
- [ ] 长 thread 不爆上下文（compact_history 触发后 token 数下降）

#### 2.4 Phase 2 完成定义

- 上述验收全过
- 用户在前端能完整看到 Plan 推进过程
- 8 步以上任务成功率 ≥ 80%（基于内部回归测试集）

---

### Phase 3 · 专业化与扩展（可选，5+ 天）

> **目标**：在 Phase 2 跑稳后，处理少量"心智负担过重"的特例。

#### 3.1 候选改造点

- [ ] 子任务（subtask）能力：Agent 自己决定要不要 spawn 一个独立上下文（**这才是多 Agent 真正派得上用场的地方** —— Agent 主动开子线程，不是 supervisor 强制路由）
- [ ] 工具结果缓存：相同 query 30 分钟内复用上次 web_search 结果
- [ ] HITL 代码确认开关（决策 2 拍板后）
- [ ] 流式 Plan：让 LLM 在 make_plan 时一边吐 step 一边渲染，提升首字延迟

> Phase 3 是滚动式的，按真实使用反馈决定优先级。

---

## 七、风险与回滚

| 风险 | 缓解 |
|---|---|
| Phase 1 改动同时跨前后端，可能出现一段时间的不可用 | 在 `unified-agent` 分支独立开发，主干保持可发布；切换前在分支跑通 §1.3 全部验收 |
| `run_in_sandbox` 工具吃下原 Coder 时，validator 配置怎么传？ | 通过 `expect_artifacts` 参数显式声明（`"chart"` / `"xlsx"` / `"pdf"` / `"none"`），LLM 自己选 |
| 删了 supervisor 后，原本"选择 Team 才有的 PDF 报告生成"会不会丢？ | 不会。能力以工具形式保留，LLM 自己会调 `generate_pdf_report` |
| 历史会话 thread_id 在新结构下能否继续？ | LangGraph checkpointer 的 state schema 变了，老 thread 不再可恢复。在切换前清理一次 checkpoint 表，或者保留 v2 端点跑老会话直到自然消亡（不推荐） |
| Plan 强制首步调用 LLM 不配合怎么办？ | system prompt 明确硬要求 + 后端 fallback：第一轮没调 make_plan 就由后端构造一个"通用单步 plan"自动写入 |

---

## 八、文件改动清单（一图流）

```
backend/
├── agent/
│   ├── single_agent.py           ✏ 改造为统一 Agent；引入 PlanState；max_steps=40
│   ├── plan_state.py             ➕ 新增（替代 v2/state.py）
│   ├── tools_heavy.py            ➕ 新增（重型工具实现）
│   ├── tools_planning.py         ➕ Phase 2 新增（make_plan / update_plan / ...）
│   ├── prompts.py                ✏ 重写 SystemPrompt，从前端搬过来
│   ├── graph_agent.py            ✓ 不动（自动化工作流仍走它）
│   └── v2/
│       ├── runtime.py            ❌ 删除
│       ├── planner.py            ❌ 删除
│       ├── tools.py              ❌ 删除
│       ├── state.py              ❌ 删除（被 plan_state.py 取代）
│       ├── llm.py                ✓ 保留
│       ├── prompts/
│       │   └── supervisor.py     ❌ 删除
│       │   └── (其余)             ✓ 保留供工具内部使用
│       ├── members/              ❌ 整体删除（base/coder/writer/researcher/responder）
│       └── infra/                ✓ 保留（executor/validator/fixer/skills/cjk）
├── api.py                        ✏ /api/chat 转发到 single_agent；删 _v2_event_to_sse 路由层
├── tools/                        ✓ 全部保留
├── skill_registry.py             ⚠ 决策 1 拍板：保留或删
└── ...

frontend/
├── src/
│   ├── components/
│   │   └── ChatView.vue          ✏ 删 mode-selector
│   ├── composables/
│   │   └── useChat.js            ✏ 大改：删 pickAgentMode / SINGLE_AGENT_BASE_PROMPT；
│   │                                 streamSingleAgent + streamChatParsed → streamAgent
│   ├── store.js                  ✏ 删 agentMode 相关字段
│   └── ...

docs/
├── unified-agent-plan.md         ➕ 本文件
├── supervisor-upgrade-plan.md    ✓ 已归档
└── skill_runtime_architecture.md ✓ 已归档（Phase 1 结束后视决策 1 决定是否删）
```

---

## 九、立即可做的第一步

如果你现在就想动起来，**Phase 1 的最小切片**是：

1. 在 `backend/agent/single_agent.py` 新增 4 个工具（`list_tables / read_table_schema / query_duckdb / run_in_sandbox`），其中 `run_in_sandbox` 内部直接 import v2 infra 的 executor_node
2. 把 `single_agent` 的 max_steps 调到 40
3. 前端 ChatView 把 mode-selector 整段注释（先不删，方便回滚）
4. `useChat.js` 把 `pickAgentMode` 直接 return 一个固定值（绕过路由）

跑通这一小步，立刻能感受到"统一入口"的差别，再决定是否继续推 Phase 1 完整版。

---

## 十、待你回复的事项

1. ❓ 决策 1：Skill Registry 留或不留？
2. ❓ 决策 2：HITL 代码确认 Phase 3 加，还是 Phase 1 内就加？
3. ❓ 决策 3：附件透传 bug 在 Phase 1 内修，还是先单独发个 Phase 0 修复版？
4. ❓ 是否同意 §九 的"立即可做的第一步"作为开干起点？

收到你的回复后我就按 Phase 0 → 1 顺序开干。
