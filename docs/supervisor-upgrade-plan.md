# Spectra Team v2 重写计划

> ✅ **已完成 / 历史文档**：v2 已成为 Team Supervisor 的唯一实现，旧 `backend/graph.py`、
> `backend/agents.py` 与 `/api/team/v2` 调试端点均已删除。前端默认且唯一走 `/api/chat`，
> 后端直接路由到 `backend/agent/v2/runtime.py`。
>
> 本文档仅作为重写过程的历史记录保留，里面 W1–W5 的迁移步骤、临时 shim 设计、
> "旧文件保持原位"等说明都是当时计划，不再反映现状。
>
> 决策时间：2026-05-16

---

## 一、核心决策

**全新平行实现 `backend/agent/v2/`，旧 Team 模式封存到 `backend/agent_legacy/`，新旧 API 并行 1 周后切流。**

| | 重写理由 |
|---|---|
| 架构对齐 | 完全采用 LobeHub 的"状态机 Supervisor + 工具化决策 + 4 种调度指令" |
| 角色精简 | 从 10 个 Agent → 4 个成员 Agent + 3 个基础设施节点 |
| 资产保留 | executor / validator / fixer / Skill Registry / CJK 字体补丁 / SSE 协议 / 前端零感知 |
| 风险控制 | 旧代码不动、新旧并行、可即时回滚 |

**借形 + 不借神**：架构借 LobeHub，但执行能力保留 Spectra 自研的"代码生成 → 沙盒 → 校验 → 修复"回路。

---

## 二、目标架构

### 2.1 三层结构（对齐 LobeHub）

```
┌──────────────────────────────────────────────────────────────┐
│                  TeamOrchestrationRuntime                     │
│                                                              │
│   ┌────────────────────┐         ┌──────────────────────┐    │
│   │  SupervisorPlanner  │ ──────→ │   AgentExecutor      │    │
│   │  纯状态机           │ ←────── │   实际派单 + LLM 调用 │    │
│   │  decide(result)     │         │   call/broadcast/    │    │
│   │  → Instruction      │         │   exec_task          │    │
│   └────────────────────┘         └──────────────────────┘    │
│           │                                │                 │
│      不调 LLM                       调 LLM、跑 Python、     │
│                                      收 artifacts            │
└──────────────────────────────────────────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │ Spectra 基础设施层  │
                     │  executor (沙盒)     │
                     │  validator (校验)    │
                     │  fixer (修复 ≤3 次)  │
                     │  skill_registry      │
                     └─────────────────────┘
```

### 2.2 4 个成员 Agent（按"产物类型"切分）

| Agent | 职责 | 产物 | 工具栈 |
|---|---|---|---|
| **`coder`** | 写 Python 处理 DuckDB 数据：清洗 / 查询 / 可视化 / 建模 / 预测 | `cleaned.xlsx` / `chart.html` / `chart.png` / 文字分析结论 | duckdb / pandas / plotly / scikit-learn / statsmodels |
| **`writer`** | 写 reportlab / python-docx 生成正式报告 / PRD / 规划文档 | `report.pdf` / `report.docx` | reportlab / python-docx |
| **`researcher`** | 联网搜索 + 网页爬取 + 结构化入库 | DuckDB `search_results` 表 + 文字摘要 | search_service / web_search 工具 |
| **`responder`** | Supervisor 自己直接回答（替代旧 FINISH 分支） | 文字 | 无工具 |

### 2.3 基础设施层（保留并搬入，**不重写**）

| 组件 | 来源 | 保留原因 |
|---|---|---|
| `executor_node` | 旧 `backend/graph.py` | E2B + 本地双引擎，错误分类，artifact 收集 |
| `validator_node` | 旧 `backend/graph.py` | 产物校验（必须有 chart / xlsx / pdf 等） |
| `fixer_node` | 旧 `backend/graph.py` | 自动修复回路 ≤3 次 |
| `skill_registry` | 旧 `backend/skill_registry.py` | 直接复用 `find_best_skill / ensure_skill_for_request` |
| `_patch_reportlab_cjk_support` | 旧 `backend/graph.py` | reportlab 中文字体补丁 |
| `Human-in-the-loop` | LangGraph checkpoint + interrupt | 涉及代码执行的安全闸 |

### 2.4 Supervisor 工具集（5 个）

| 工具 | 行为 | 备注 |
|---|---|---|
| `assign(agent_id, instruction)` | 派单一同步 | 替代旧 `next_node` 单选 |
| `broadcast(agent_ids, instruction)` | 多 Agent 并行同步 | 共享主对话上下文 |
| `execute_task(agent_id, title, task, timeout=600)` | 单人后台异步任务 | 写报告 / 长 PRD 不阻塞主对话 |
| `execute_tasks([{agent_id, task}, ...])` | 多人并行后台任务 | 同一 Agent 可派多份不同任务 |
| `respond(text)` | Supervisor 直接回答（无需派单） | 替代旧 FINISH |

不实现：`vote` / `delegate`（数据分析场景用不到）。

### 2.5 状态机决策规则（对齐 LobeHub）

```
ExecutorResult:
  ├── type="init"
  │   → call_supervisor (round=0)
  │
  ├── type="supervisor_plan"
  │   解析 LLM tool_call:
  │   ├── assign         → CallAgent
  │   ├── broadcast      → ParallelCallAgents
  │   ├── execute_task   → SpawnBackgroundTask
  │   ├── execute_tasks  → SpawnBackgroundTasks
  │   ├── respond        → ReplyAndFinish
  │   └── finish         → Finish
  │
  ├── type="agent_done" / "agents_done" / "task_done"
  │   ├── 该 Agent 失败且未触发自动修复 → 上报给 supervisor 决定
  │   ├── round >= max_rounds(8)        → Finish
  │   └── 否则                           → call_supervisor
  │
  └── type="all_tasks_done"
      → call_supervisor 做最终汇总
```

**关键差异（与 LobeHub 不同）**：Spectra 任何 Agent 输出失败时，**先经 validator → fixer 修复回路**，最多 3 次，仍失败才把"修复后仍失败"的结果交给 Supervisor 决定下一步。

---

## 三、目录结构

```
backend/
├── agents.py                     # 旧版 Team Supervisor 实现（W1–W4 原地保留，仅加废弃注释）
├── graph.py                      # 同上
│
├── agent/
│   ├── single_agent.py           # 保留不动 ❗ 仍 import backend.agents._create_llm
│   ├── graph_agent.py            # 保留不动
│   ├── prompts.py                # 保留不动
│   │
│   └── v2/                       # 新 Team Supervisor 实现
│       ├── __init__.py
│       ├── runtime.py            # TeamOrchestrationRuntime（step / run）
│       ├── planner.py            # SupervisorPlanner（纯状态机）
│       ├── tools.py              # 5 个工具的 LangChain @tool 定义
│       ├── state.py              # TeamState（消息/轮次/产物/Skill 上下文）
│       ├── prompts/
│       │   ├── supervisor.py     # Supervisor system prompt（含 6 种 Pattern）
│       │   ├── coder.py
│       │   ├── writer.py
│       │   ├── researcher.py
│       │   └── responder.py
│       ├── members/
│       │   ├── base.py           # BaseAgent：包装 prompt → LLM 调用 → 校验 → 返回
│       │   ├── coder.py
│       │   ├── writer.py
│       │   ├── researcher.py
│       │   └── responder.py
│       ├── infra/
│       │   ├── executor.py       # 直接 import 旧 executor 函数（不复制代码）
│       │   ├── validator.py
│       │   ├── fixer.py
│       │   └── cjk_patch.py
│       └── llm.py                # 直接 import backend.agents._create_llm（不复制）
│
├── api.py                        # 加 /api/team/v2 端点；W5 才让 /api/chat 切到 v2
└── ...（其余文件不动）
```

**为什么旧文件不搬迁**：`backend/agent/single_agent.py` 从 `backend.agents` 导入下划线
开头的 `_create_llm`，用 `from backend.agent_legacy.agents import *` 这种 shim 取不到，
强行搬会破坏 `/api/agent/chat`。所以 W1–W4 期间旧文件留在原位，v2 用 `from
backend.agents import _create_llm` 直接复用。W5 sunset 时再做物理搬迁，那时
single_agent 已改造为从 v2 借用 LLM 工厂。

---

## 四、实施周表

每周一个里程碑，每周末必须出可演示的 demo。

### W1：骨架搭建（3 天）

**目标**：v2 能跑通最简单的一句问候，不调 LLM 时也能走完整状态机循环。

- [ ] 把 `backend/graph.py` / `backend/agents.py` 整体迁到 `backend/agent_legacy/`
- [ ] 原位留 shim：`backend/graph.py` → `from backend.agent_legacy.graph import *`
- [ ] 新建 `backend/agent/v2/` 整套骨架文件（空函数 + TODO）
- [ ] 实现 `state.py`：`TeamState = {messages, round_count, max_rounds, current_instruction, parallel_outputs, pending_tasks, artifacts}`
- [ ] 实现 `planner.py`：纯状态机，**不调 LLM**，所有路径用单元测试覆盖
- [ ] 实现 `tools.py` 的 5 个工具（先只返回 schema，不绑定 LLM）
- [ ] 实现 `runtime.py` 的 `step()` 与 `run()` 循环
- [ ] 接入 `responder` Agent（不需要执行器，直接返回文字）
- [ ] 新增 API `POST /api/team/v2`（SSE，事件协议同 `/api/chat`）
- [ ] 前端 `useChat.js` 加 `streamTeamV2`，开关用 `localStorage.getItem('team_version') === 'v2'`

**验收**：
- "你好" → Supervisor 选 `respond` → 前端正确显示文字
- `pytest tests/v2/test_planner.py` 全绿（mock LLM tool_call 测各分支）

### W2：coder Agent + 基础设施嫁接（4 天）

**目标**：跑通"上传 csv → 让它做分析 → 出图"的完整数据分析路径。

- [ ] `infra/executor.py` 从 `agent_legacy.graph` 直接 re-export `executor_node` 等函数
- [ ] `infra/validator.py` 同上
- [ ] `infra/fixer.py` 同上
- [ ] `members/base.py` 抽出公共流程：
  ```
  def execute(self, instruction, context):
      # 1. 调 LLM 生成代码 + 自然语言摘要
      # 2. 调 executor 执行
      # 3. 调 validator 校验产物
      # 4. 失败则调 fixer 重试，最多 3 次
      # 5. 返回 AgentResult{reply, artifacts, code, status}
  ```
- [ ] `members/coder.py`：合并旧 cleaner + analyzer + visualizer + predictor 的 prompt 精华，输出新 prompt
- [ ] `tools.py` 的 `assign` 工具真正调用 `members/coder.py`
- [ ] `planner.py` 把 `assign` 决策路由到 `coder`
- [ ] runtime 把 `members/coder.py` 的产物转成 SSE 事件（`chart`/`file`/`code`/`reply`/`runtime`）

**验收**：
- 上传一个 csv → "帮我看下销售趋势" → coder 写代码 → 沙盒执行 → chart.html 落到 artifacts → 前端正确显示
- 故意让 LLM 写错代码 → fixer 自动修复 → 通过

### W3：writer + researcher + Skill 接入（4 天）

**目标**：跑通"写一份完整 PDF 财报"和"搜索竞品 X 的最新动态"。

- [ ] `members/writer.py`：合并旧 reporter + planner 的 prompt（去掉所有"如果是财报就照模板写"的暗示）
- [ ] writer 的 prompt 强约束：必须用 reportlab/python-docx + `print('REPORT_GENERATED:xxx')`
- [ ] writer 的 validator 加强：用 `pdfplumber` 抽 PDF 文本，断言长度 > 200 且包含数字
- [ ] `members/researcher.py`：复用旧 `_build_search_data_snippet` 的预获取数据 → 字面量注入逻辑
- [ ] Skill Registry 接入：`writer` 和 `researcher` 在执行前调 `ensure_skill_for_request(task, agent_id)`
- [ ] 把现有 `.trae/skills/` 中的 `agent: reporter` / `agent: planner` 改为 `agent: writer`
- [ ] 删除 `.trae/skills/pdf-autofill/`（form_filler 不再存在）
- [ ] 删除 `backend/pdf_autofill_engine.py`、`backend/report_templates.py`

**验收**：
- "帮我写一份 2025 年星辰科技年度财报 PDF" → writer 调用 → PDF 生成且中文正常
- "调研 Anthropic 最近的产品动态" → researcher 联网搜 → DuckDB 入库 → 文字摘要

### W4：并行 + 异步（3 天）

**目标**：跑通 broadcast 和 execute_task 两种高级调度。

- [ ] `runtime.py` 实现 `parallel_call(agent_ids, instruction)`：用 `asyncio.gather`，独立 ContextVar 隔离 token usage
- [ ] `state.py` 新增 `parallel_outputs: dict[agent_id, AgentResult]`，下一轮 supervisor 能看到所有人的回复
- [ ] SSE 事件新增：`parallel_start` / `parallel_done` / 每个成员的 `agent_message`
- [ ] 前端 RuntimePanel 新增"并行调用"分区
- [ ] `state_store` 新增 `agent_tasks` 表：`task_id / agent_id / status / result_json / created_at`
- [ ] 复用 `task_executor` 线程池跑 `execute_task`（每个任务入口重新 `begin_request`）
- [ ] SSE 新增 `task_pending` / `task_progress` / `task_completed`
- [ ] 前端 RuntimePanel 新增"后台任务"分区
- [ ] 后台任务结果回来后，自动作为 `task_done` ExecutorResult 注入下一轮 supervisor

**验收**：
- "对这份销售数据，让 coder 分析、researcher 看看行业对标、再给点建议" → broadcast 三人 → 结果合并
- "写一份完整的 SaaS 产品 PRD" → 立刻收到 task_id，期间能继续聊别的，2 分钟后 PDF 推送回来

### W5：切流 + 旧代码下线（2 天）

**目标**：v1 sunset，目录干净。

- [ ] 默认走 v2，env var `SPECTRA_TEAM_VERSION=v1` 可切回旧的（保留 1 个发版周期）
- [ ] `/api/chat` 内部转发到 v2（保持外部 URL 不变）
- [ ] 跑完整回归：旧 `tests/test_graph.py` 用例改造成测 v2，全绿
- [ ] 删除 `backend/agent_legacy/`（确认无引用后）
- [ ] 删除 `backend/agents.py` / `backend/graph.py` 的 shim
- [ ] 删除 `tests/test_pdf_autofill.py` / `tests/test_pdf_font_fallback.py`（form_filler 与硬编码模板已不存在）
- [ ] README / `docs/skill_runtime_architecture.md` / `docs/pdf_autofill_engine.md` 更新或删除
- [ ] 升级 `agents.py` 与 `graph.py` 根目录 shim：直接指向 `backend.agent.v2`

**验收**：
- 仅剩 v2 代码、所有测试绿、用户行为相对 v1 完全等价 + 多了并行/异步能力

---

## 五、API & 前端切流

### 5.1 后端

```python
# backend/api.py 中新增
@app.post("/api/team/v2")
async def team_v2(request: Request):
    """Team Supervisor v2 SSE 端点"""
    ...

# /api/chat 在 W5 切到 v2
@app.post("/api/chat")
async def chat(request: Request):
    if os.environ.get("SPECTRA_TEAM_VERSION", "v2") == "v1":
        return await _chat_v1_legacy(request)
    return await _chat_v2(request)
```

### 5.2 前端

```js
// useChat.js
const teamVersion = localStorage.getItem('team_version') || 'v2'
const endpoint = teamVersion === 'v2' ? '/api/team/v2' : '/api/chat'
```

**SSE 事件协议**保持不变（`node` / `runtime` / `message` / `chart` / `file` / `report` / `code` / `reply` / `artifacts` / `usage` / `done` / `error` / `ping`），新增：

| 新事件 | 用途 |
|---|---|
| `agent_message` | 单个成员 Agent 的可见输出（broadcast 场景多次出现） |
| `parallel_start` / `parallel_done` | 并行调用开始/完成 |
| `task_pending` / `task_progress` / `task_completed` | 后台异步任务进度 |
| `supervisor_decision` | Supervisor 的 tool_call 决策（含选了哪个工具、派给谁） |

---

## 六、prompt 草稿（可直接落地）

### 6.1 Supervisor system prompt（节选）

```
你是 Spectra 数据分析团队的 Supervisor。

【可用成员】
- coder：写 Python 处理 DuckDB 数据。清洗/查询/可视化/建模/预测都找他。产出 .xlsx/.html/.png 或文字。
- writer：用 reportlab/python-docx 写正式报告（PDF/DOCX）。年报/PRD/规划/分析报告都找他。
- researcher：联网搜索与爬取。涉及最新行业动态/新闻/竞品/政策都找他。
- responder：你自己直接答（文字回复）。简单问候/概念解释/无需查数据时用。

【当前数据库 schema】
{schema}

【决策规则】
1. 用户在闲聊或问通用知识 → respond
2. 用户提到 csv/excel/数据/分析/图表/趋势/聚类/预测 → assign(coder, ...)
3. 用户要 PDF / 报告 / PRD / 规划 → assign(writer, ...)
4. 用户要最新信息/搜索/调研外部 → assign(researcher, ...)
5. 复杂任务（如"分析销售并写一份报告"）→ broadcast 或 sequential assign
6. 长任务（"写完整 PRD"）→ execute_task
7. 多个独立子任务 → execute_tasks 并行

【6 种工作流模式】
- Discussion：让 coder/researcher 各自给意见 → broadcast
- Sequential：coder 出分析 → writer 整理成 PDF → assign 链
- Focused：明确单人任务 → assign
- Single Async：长任务 → execute_task
- Parallel Tasks：3 个独立调研 → execute_tasks
- Hybrid：先讨论达成共识，再 execute_task 落地

每轮你必须调用恰好一个工具。最多 8 轮。
```

### 6.2 coder system prompt（节选）

```
你是数据工程师，写 Python 代码处理 DuckDB 数据库 `data.duckdb`。

【schema】
{schema}

【任务类型识别】
- 用户提到"清洗/去重/缺失值" → 输出 cleaned_data.xlsx + print("CLEANED_DATA_GENERATED:xxx")
- 用户提到"趋势/分布/对比/可视化" → 输出 chart.html + chart.png + print("CHART_GENERATED:xxx" / "CHART_PNG_GENERATED:xxx")
- 用户提到"预测/建模/聚类/回归" → 输出图表 + 评估指标（RMSE/Accuracy 等）
- 用户只要"看一下/统计/分析" → print 输出文字结论即可

【硬约束】
- 必须用 ```python ... ``` 包裹完整可执行代码
- 禁止 pip install、subprocess、os.system
- 用 plotly_dark template + #1e1e2e 背景，文字 #cdd6f4
- 通过 duckdb.connect('data.duckdb') 读写
```

### 6.3 writer system prompt（节选）

```
你是技术写作专家，用 reportlab 或 python-docx 生成正式文档。

【任务】
{task_goal}

【上下文产物】
{upstream_artifacts}  ← 来自 coder 的 chart.png 路径，必须用 reportlab.platypus.Image 嵌入

【硬约束】
- 优先生成 PDF（reportlab），中文必须能正常显示（系统会自动注入 CJK 字体）
- 必须 print("REPORT_GENERATED:xxx.pdf") 通知执行器
- 数据必须来自 duckdb.connect('data.duckdb') 真实查询，禁止编造数字
- 报告至少包含：摘要 / 数据概览 / 关键发现 / 详细分析 / 结论与建议
- 如有图表 PNG，用 reportlab.platypus.Image 嵌入对应章节
```

### 6.4 researcher system prompt（节选）

```
你是联网情报员。系统已通过 search_service 预获取了搜索结果，
你只负责把这些固化为 Python 字面量的数据存入 DuckDB 并输出报告摘要。

【预获取数据】
{search_data_snippet}  ← _SEARCH_RESULTS / _CRAWLED_RESULTS

【硬约束】
- 不允许 import search_service / 调用 search() / urllib / BeautifulSoup
- 直接使用 _SEARCH_RESULTS，不要做 URL 过滤、域名筛选、去重
- 数据存入 DuckDB 表 search_results
- print 输出可读报告
```

### 6.5 responder system prompt（节选）

```
你是 Spectra 团队对外发言人，处理简单问候 / 概念解释 / 不需要数据的问题。
基于上下文用中文直接回答，简洁专业。如果发现需要数据/报告/搜索，
说"这个需要让 coder/writer/researcher 来做"，由 Supervisor 重新决策。
```

---

## 七、关键设计抉择

### 7.1 为什么 Supervisor 拆成"状态机 + LLM"两层

**单测可重放、不烧 token**。状态机部分用 mock tool_call 就能覆盖所有路径。
旧版 `supervisor_agent` 把决策与回答耦合在一起，导致路由测试必须真的调 LLM。

### 7.2 为什么把 cleaner/analyzer/visualizer/predictor 合成 `coder`

四者本质都是"写 Python 代码处理 DuckDB"，区别只在产物类型。validator 已按产物校验，
让 LLM 自己根据任务描述选方法（用 sklearn 还是 statsmodels）比让 supervisor 4 选 1 更准。
这是把 Spectra 决策面从"业务领域"切到"产物类型"的核心动作。

### 7.3 为什么 skill_builder 不再是 Agent 节点

它现在做的事就是"读 task_goal + 写一个 SKILL.md 文件"，包装成 Agent 没有意义。
v2 中降级为 `infra/skill_registry.ensure_skill_for_request()` 调用，
由 writer / researcher 在执行前自己取 skill。

### 7.4 Agent 级模型映射

```python
AGENT_MODEL_DEFAULTS = {
    "coder":      "qwen-plus",   # 代码生成快即可
    "writer":     "qwen-max",    # 长文本质量重要
    "researcher": "qwen-plus",
    "responder":  "qwen-plus",
    "supervisor": "qwen-plus",   # 决策快比强重要
}
```

用户在前端选的 model 仍然优先生效。

### 7.5 现有 SSE 事件协议保持向后兼容

旧前端不改任何代码也能正常工作。新功能（broadcast / async task）通过新增事件类型实现，
旧客户端只是看不到这些新事件而已。

---

## 八、风险与缓解

| 风险 | 缓解 |
|---|---|
| `coder` 一个 prompt 覆盖 4 种产物，LLM 偷懒只输出文字 | prompt 强约束 + validator 强校验：要画图必须有 chart_png；要清洗必须有 .xlsx；不达标进 fixer 重试 |
| `writer` 失去模板兜底，PDF 质量回归 | prompt 给章节大纲 + reportlab 调用骨架代码 + pdfplumber 抽文本校验长度 |
| 并行调用 DuckDB 写冲突 | broadcast 内的 Agent 默认只读 DuckDB；需要写入时改为顺序 assign |
| 后台任务结果回来时主对话已断 | 任务结果落 SQLite + 用户下次发消息时自动注入"上次后台任务结果是 X" |
| max_rounds=8 不够用 | Supervisor `respond` 显式终止；轮次上限只是兜底；复杂任务 supervisor 会自动 chunk |
| LangGraph checkpointer 与新 TeamState 不兼容 | TeamState 加 `version: int` 字段，旧 checkpoint 视为不兼容直接丢弃（仅影响 1 周内的中断会话） |

---

## 九、产品瘦身（一次性清理，与 W3 同步执行）

| 删除项 | 替代方案 |
|---|---|
| `backend/pdf_autofill_engine.py` 整个文件 | 删除。PDF 模板填充场景太定制 |
| `backend/report_templates.py` 整个文件 | 删除。writer 用 LLM 自由生成代码 |
| `form_filler_agent` | 删除。需求合并进 writer |
| `state.execution_mode` 的 `template` / `fallback_template` 分支 | 删除。writer 永远走 LLM 实时生成 |
| `.trae/skills/pdf-autofill/` | 删除目录 |
| `tests/test_pdf_autofill.py` | 删除 |
| `tests/test_pdf_font_fallback.py` | 改造为测 `_patch_reportlab_cjk_support` 本身 |
| `docs/pdf_autofill_engine.md` | 删除 |

---

## 十、验收清单（W5 末必须全过）

- [ ] 上传 csv → "做月度销售分析" → coder 出图 + 文字结论 ✓
- [ ] "写一份星辰科技 2025 年报 PDF" → writer 出 PDF + 中文正常 ✓
- [ ] "调研 Anthropic 最近动态" → researcher 联网 + 入库 + 摘要 ✓
- [ ] "你好" → responder 文字回应（不调任何 Agent） ✓
- [ ] "对这份数据，coder 分析、researcher 调研、给我建议" → broadcast 并行 ✓
- [ ] "写完整 SaaS PRD" → execute_task 后台 + 期间能继续聊 ✓
- [ ] 故意让 LLM 写错代码 → fixer 自动修复 ≤3 次 ✓
- [ ] Skill Registry：writer 复用 `analysis-report` skill；新需求自动创建新 skill ✓
- [ ] Token usage 按 model 分项展示在 RuntimePanel ✓
- [ ] 历史对话跨浏览器同步（已完成）继续工作 ✓
- [ ] 旧 `/api/chat` 行为完全等价（v2 默认 + v1 可降级）✓
- [ ] `backend/agent_legacy/` 删除后所有测试仍绿 ✓

---

## 十一、不在本次范围

- LangGraph 自己重写（checkpointer / interrupt 还够用，不重造轮子）
- 多用户隔离（`conversation_store` 已预留 `user_id`，等接入登录后再做）
- `vote` / `delegate` 工具（场景极少）
- Agent 配置可视化编辑（先跑通核心，UI 后置）
- DuckDB 不再 copy 整库（独立优化项，与本次重写解耦）

---

## 十二、立即行动

W1 第一天就做的事（**安全策略：旧代码原地不动**）：

1. `git checkout -b team-v2-rewrite`
2. `backend/graph.py` 和 `backend/agents.py` **保持原位**，仅在文件顶部加废弃注释
   说明"v2 实现在 `backend/agent/v2/`，本文件仅供旧 `/api/chat` 与 single_agent 复用 `_create_llm`"。
   **不做 git mv** —— 因为 `backend/agent/single_agent.py` 从 `backend.agents` 导入 `_create_llm`
   （下划线开头），用 `from x import *` 这种 shim 取不到，硬搬会破坏单 Agent 模式
3. 创建 `backend/agent/v2/` 整套空骨架（state.py / planner.py / runtime.py / tools.py / members/ stubs）
4. 实现 `backend/agent/v2/state.py`（TeamState TypedDict + 工厂函数）
5. 实现 `backend/agent/v2/planner.py` 的纯状态机（含完整单测，**不调 LLM**）
6. 跑一遍 `python -m unittest discover tests`，确认旧测试全绿
7. 跑一遍 `pytest tests/v2/test_planner.py`（新增），确认状态机所有路径覆盖

W5 sunset 时再做物理搬迁：把 `backend/agents.py` 与 `backend/graph.py` 移到 `backend/agent_legacy/`，
那时 `single_agent.py` 已经改造为从 v2 借用 LLM 工厂，旧文件可彻底下线。

**核心约束（用户明确指出）**：
- 整个 v2 重写过程**不允许影响 `backend/agent/single_agent.py` 与 `/api/agent/chat`**
- 整个 v2 重写过程**不允许改前端代码**（SSE 协议保持向后兼容）

确认后开工。
