# Spectra Phase 2 规划 —— MTC 模式对齐

> 起草时间：2026-05-21
> 参考产品：Trae Solo 网页 MTC（More Than Coding）模式
> 前置文档：[unified-agent-plan.md](./unified-agent-plan.md) Phase 1 已完成，Phase 2 待细化

---

## 一、MTC 模式核心 UX 分析

### 1.1 Trae Solo MTC 的三面板布局

```
┌─────────────┬───────────────────────┬─────────────────┐
│  Task Panel  │      Chat Panel       │   Tool Panel    │
│  (左侧 280px) │     (中间弹性)          │  (右侧 340px)    │
│              │                       │                 │
│  📋 任务清单   │  用户: 帮我分析销售数据   │  🔧 工具调用实时流  │
│  ✓ 步骤1     │                       │  list_tables()  │
│  ⟳ 步骤2     │  Agent: 好的，我先探索  │  → orders, ...  │
│  ○ 步骤3     │  数据表结构...          │                 │
│  ○ 步骤4     │                       │  📎 产物集中展示   │
│              │                       │  chart.html     │
│  进度: 2/4   │                       │  report.pdf     │
│  ██████░░ 50%│                       │                 │
└─────────────┴───────────────────────┴─────────────────┘
```

### 1.2 Spectra 现有布局映射

| MTC 面板 | Spectra 对应 | 当前状态 | Phase 2 改造 |
|----------|-------------|---------|-------------|
| Task Panel | Sidebar (`LeftSidebar.vue`) | 目前是会话历史列表 | 新增"任务规划"Tab，展示 plan checklist |
| Chat Panel | ChatView | 已有对话流 | 保持，但 tool_call 气泡关联到 plan step |
| Tool Panel | RuntimePanel (`RuntimePanel.vue`) | 已有基础框架（执行状态/时间线/产物） | 重构为 plan 驱动视图 + 产物面板 |

### 1.3 MTC 关键交互模式

**Plan → Execute 自动流转**（无需人工审核）：
1. 用户发送任务
2. Agent 自动调 `make_plan` 拆解步骤 → 前端渲染 checklist
3. 按步骤顺序执行，实时更新状态（pending → running → done/failed）
4. 当前执行步骤高亮，失败步骤红色标记
5. 产物自动出现在右侧 Tool Panel
6. 全部完成后 plan 折叠为摘要

**与 Spectra 当前差异**：
- Spectra 有 RuntimePanel，但只展示原始事件时间线，没有 plan 视图
- Spectra 的 taskTodos 是前端自发模拟的，没有后端 plan 状态同步
- tool_call 没有关联到具体 plan step

---

## 二、Spectra MTC 对齐方案

### 2.1 整体架构

```
用户发送消息
     │
     ▼
┌──────────────────────────────────────────────────────┐
│  backend/api.py  POST /api/chat                       │
│                                                      │
│  1. init_plan()  ← ContextVar                         │
│  2. astream_events 循环:                               │
│     - 检测 plan_state 变化 → 发射 plan_* SSE 事件       │
│     - on_tool_start → 发射 tool_start (含 plan_step)    │
│     - 其他事件保持不变                                   │
└──────────────────────────────────────────────────────┘
     │  SSE stream
     ▼
┌──────────────────────────────────────────────────────┐
│  frontend/useChat.js                                  │
│                                                      │
│  处理 plan_created / plan_updated / plan_revised      │
│  → 更新 store.taskPlan                                │
│  处理 tool_start → 关联到当前 plan step                 │
└──────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────┬────────────────┬──────────────────────┐
│  Sidebar     │  ChatView      │  RuntimePanel        │
│  (plan tab)  │  (tool 气泡     │  (plan 进度 + 产物)   │
│              │   关联 step)    │                      │
└──────────────┴────────────────┴──────────────────────┘
```

### 2.2 不照搬 MTC 的地方

| MTC 做法 | Spectra 做法 | 原因 |
|----------|-------------|------|
| 三面板固定布局 | 保持现有 Sidebar + Chat + RuntimePanel 可折叠 | Spectra 用户习惯已形成，2560px 以下屏幕三面板太挤 |
| Task Panel 始终可见 | Plan 在 RuntimePanel 顶部显示，Sidebar 保留会话历史 | RuntimePanel 折叠时可在 ChatView 顶部显示 mini plan bar |
| 人工点击"执行"才开始 | 全自动执行 | 对标 Claude Code/Cursor Composer，非 MTC 的审批流 |
| 单次任务结束后 plan 消失 | plan 持久化到 conversation，历史回放可见 | 便于审计和复现 |

---

## 三、数据模型：PlanState 前端表示

### 3.1 后端 `plan_state.py`（已完成，无需改动）

ContextVar 中的 plan dict：
```python
plan = {
    "steps": [
        {"id": "s1", "description": "探索 orders 表结构", "status": "done", "note": "", "started_at": 1716300000, "finished_at": 1716300012},
        {"id": "s2", "description": "按月聚合销售额", "status": "running", "note": "", "started_at": 1716300012, "finished_at": 0},
        {"id": "s3", "description": "生成趋势图", "status": "pending", "note": "", "started_at": 0, "finished_at": 0},
    ],
    "revision": 0,
    "finished": False,
    "finish_reason": "",
    "created_at": 1716300000,
}
```

### 3.2 前端 store 新增字段

```javascript
// store.js 新增
taskPlan: {
  steps: [],          // [{id, description, status, note, startedAt, finishedAt}]
  revision: 0,
  finished: false,
  finishReason: '',
  createdAt: 0,
  currentStepId: null,  // 当前正在执行的 step（前端推导）
  progress: 0,          // 0-100
},
```

### 3.3 SSE 事件协议

| 事件名 | 触发时机 | payload |
|--------|---------|---------|
| `plan_created` | `make_plan` 被调用后 | `{steps: [...], revision: 0}` |
| `plan_updated` | `update_plan` 被调用后 | `{step_id, status, note}` |
| `plan_revised` | `revise_plan` 被调用后 | `{reason, steps: [...], revision: N}` |
| `plan_finished` | `finish` 被调用后 | `{summary, finish_reason}` |
| `tool_start` | 工具开始执行（已有，扩展） | 新增 `plan_step_id` 字段 |

---

## 四、实施步骤

### Step 1: 完善 `single_agent.py` 规划循环（已完成 60%）

**状态**: plan_state.py + tools_planning.py 已完成，single_agent.py 部分完成

**待完成**:
- [ ] `call_tools` 节点：检测 `make_plan` 调用结果 → 设置 `plan_made = True`
- [ ] `call_tools` 节点：检测 `finish` 调用 → 路由到 END
- [ ] Router `after_tools`：检测 `plan_needs_revision()` → 返回 `"force_summarize"` 并在 prompt 中注入 revice 指令
- [ ] `call_llm` 节点：plan_made 状态回传正确

### Step 2: 更新 `api.py` —— plan 事件发射

**目标**: 在 SSE 循环中检测 plan 状态变化并发射事件

实现思路 —— 在 `agent_event_generator()` 中：
```python
# 每个 event 处理后检测 plan 变化
prev_plan_snapshot = None

async for event in single_graph.astream_events(...):
    # ... 现有事件处理 ...
    
    # 检测 plan 变化
    plan = get_plan()
    if plan:
        plan_snap = _plan_snapshot(plan)
        if plan_snap != prev_plan_snapshot:
            # 发射对应事件
            if plan.get("_plan_created"):
                yield {"event": "plan_created", ...}
            elif plan.get("_plan_updated"):
                yield {"event": "plan_updated", ...}
            # ...
            prev_plan_snapshot = plan_snap
```

实际实现用 plan dict 中的 `_plan_created` / `_plan_updated` / `_plan_revised` / `_plan_finished` 标记位来判断。

### Step 3: 更新 `agent-base.md` prompt

在 `.trae/prompts/agent-base.md` 中新增规划循环指引：

```markdown
## 任务规划循环（核心工作流）

对于任何非闲聊请求，必须按以下流程执行：

1. **首轮**：调用 `make_plan(steps_json)` 拆解任务。即使是简单任务也至少建一个单步计划。
2. **执行中**：每开始一个步骤调 `update_plan(step_id, "running")`，完成后调 `update_plan(step_id, "done", note)`。
3. **遇到困难**：某步骤失败后先重试。连续失败 3 次 → 调 `revise_plan(reason, new_steps_json)` 换路线。
4. **发现新需求**：调 `add_step(after_step_id, description)` 插入。
5. **全部完成**：调 `finish(summary)` 收尾。

**关键规则**：
- 不要跳过 make_plan，这不是可选的
- 每个 step 的 tool 调用完成后立即 update_plan，保持进度可见
- finish 之前确认所有步骤都是 done 或 failed
```

### Step 4: 前端 `useChat.js` —— 处理 plan SSE 事件

```javascript
// 新增 SSE 事件处理器
case 'plan_created':
  store.taskPlan = {
    steps: data.steps.map(s => ({...s, startedAt: s.started_at || 0, finishedAt: s.finished_at || 0})),
    revision: data.revision || 0,
    finished: false,
    finishReason: '',
    createdAt: Date.now(),
    currentStepId: data.steps.length > 0 ? data.steps[0].id : null,
    progress: 0,
  }
  break

case 'plan_updated':
  const step = store.taskPlan.steps.find(s => s.id === data.step_id)
  if (step) {
    step.status = data.status
    if (data.note) step.note = data.note
  }
  // 更新 currentStepId 和 progress
  updatePlanProgress()
  break

case 'plan_revised':
  store.taskPlan.steps = data.steps.map(s => ({...s, ...}))
  store.taskPlan.revision = data.revision
  updatePlanProgress()
  break

case 'plan_finished':
  store.taskPlan.finished = true
  store.taskPlan.finishReason = data.finish_reason || 'completed'
  break
```

`tool_start` 扩展 —— 自动关联当前 step：
```javascript
// 当 tool_start 带有 plan_step_id 时，关联到对应 step
// 否则使用 currentStepId（第一个 running 状态的 step）
```

### Step 5: 前端 `RuntimePanel.vue` —— Plan 视图

在 RuntimePanel 顶部新增"任务规划"section（在执行状态上方）：

```
┌──────────────────────────┐
│ 📋 任务规划         2/4   │
│ ██████████░░░░░ 50%      │
│                          │
│ ✓ 1. 探索 orders 表结构   │
│ ⟳ 2. 按月聚合销售额       │ ← 当前执行（蓝色高亮 + spinner）
│ ○ 3. 生成趋势图           │
│ ○ 4. 撰写分析报告         │
│                          │
│ ⚠ 步骤2 执行失败：        │  ← 仅失败时显示
│   connection timeout     │
└──────────────────────────┘
```

视觉规范：
- `pending` → 灰色圆点 `○`
- `running` → 蓝色旋转 spinner `⟳`
- `done` → 绿色对勾 `✓`
- `failed` → 红色叉号 `✗` + 红色背景行
- 当前步骤整行加蓝色左边框
- 计划完成后自动折叠为一行摘要：`✓ 任务完成 · 4/4 步骤 · 用时 2m34s`

### Step 6: 前端 `RuntimePanel.vue` —— 产物面板增强

复用现有"产出文件"section，增强展示：
- 按 plan step 分组显示产物
- 每个产物显示来源 step + 生成时间
- 支持预览（HTML 图表 iframe 内嵌）和下载

### Step 7: ChatView tool 气泡关联 step

在 `ChatMessage.vue` 的 tool_call 气泡上：
- 显示 `步骤 s2 → web_search` 而非单纯的 `web_search`
- 点击步骤编号跳转到 RuntimePanel 对应 step

---

## 五、待完成清单（按优先级）

| # | 任务 | 文件 | 预估 |
|---|------|------|------|
| 1 | single_agent.py 规划循环收尾 | `backend/agent/single_agent.py` | 0.5h |
| 2 | agent-base.md prompt 更新 | `.trae/prompts/agent-base.md` | 0.5h |
| 3 | api.py plan 事件发射 | `backend/api.py` | 1h |
| 4 | useChat.js plan 事件处理 | `frontend/src/composables/useChat.js` | 1h |
| 5 | RuntimePanel plan 视图 | `frontend/src/components/RuntimePanel.vue` | 2h |
| 6 | store.js taskPlan 字段 | `frontend/src/store.js` | 0.25h |
| 7 | ChatMessage tool 气泡 step 关联 | `frontend/src/components/ChatMessage.vue` | 0.5h |
| 8 | 端到端测试验证 | 手动测试 | 1h |

---

## 六、不纳入 Phase 2 的内容（→ Phase 3）

- **流式 Plan 生成**（让 LLM 一边吐 step 一边渲染）—— 需要改造 make_plan 的 streaming 行为
- **子任务 spawn**（Agent 主动开独立上下文处理子任务）—— 需要全新架构
- **HITL 审核开关**（代码执行前人工确认）—— unified-agent-plan.md 决策 2
- **工具结果缓存**（相同 query 30 分钟内复用）—— 纯后端优化
- **Plan 模板**（预设常见任务的 plan 骨架）—— 产品化功能

---

## 七、与 `unified-agent-plan.md` 的关系

本文件是对 `unified-agent-plan.md` Phase 2 章节的细化和 MTC 对齐。两者关系：

- `unified-agent-plan.md`：整体架构决策 + Phase 0/1/2/3 分阶段规划
- `mtc-phase2-plan.md`（本文件）：Phase 2 的详细执行方案，聚焦 MTC UX 对齐

Phase 1（统一入口、砍 v2、prompt 文件化、附件透传）已完成，不在本文件范围内。
Phase 3（子任务、缓存、HITL、流式 plan）保持原文档定义不变。
