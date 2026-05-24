# LobeHub 多 Agent Supervisor 模式分析

## 一、用户视角：没有 "模式选择器"

打开 LobeHub 聊天页面，**没有任何 "切换模式" 的 UI 控件**。模式完全取决于你点进的是谁：

| 你点进 | 系统用 | 你怎么感知 |
|--------|--------|-----------|
| 一个 Agent | GeneralChatAgent（单 Agent + 工具） | 左上角显示 Agent 名字 |
| 一个 Group | Supervisor 编排模式 | 左上角显示 Group 名字，消息会标注发言人 |

用户心智是 "我在跟一个团队聊天"，系统在幕后做的事是 "Supervisor 调度成员 Agent"。

---

## 二、架构总览：三层结构

```
┌──────────────────────────────────────────────────────────┐
│                 GroupOrchestrationRuntime                 │
│                                                          │
│   ┌────────────────────┐        ┌──────────────────┐     │
│   │     Supervisor      │ ────→ │    Executors     │     │
│   │   (State Machine)   │ ←──── │ (Execution Layer) │     │
│   │    决策下一步做什么    │        │   实际执行指令     │     │
│   └────────────────────┘        └──────────────────┘     │
│            │                            │                │
│      纯状态机，不调 LLM             调用 LLM / 发消息     │
│      代码: GroupOrchestration       代码: createGroup-    │
│            Supervisor.ts                 Orchestration    │
│                                          Executors()      │
└──────────────────────────────────────────────────────────┘
```

| 层 | 组件 | 代码位置 | 职责 |
|----|------|---------|------|
| **Supervisor（状态机）** | `GroupOrchestrationSupervisor` | `packages/agent-runtime/src/groupOrchestration/GroupOrchestrationSupervisor.ts` | 接收 ExecutorResult → 返回 SupervisorInstruction，**纯逻辑，不调 LLM** |
| **Supervisor LLM** | 群组中的 Supervisor Agent | 运行时由 `AgentRuntime` 调用 | 用工具调用做实际决策：选哪个 Agent、发什么指令 |
| **Runtime** | `GroupOrchestrationRuntime` | `packages/agent-runtime/src/groupOrchestration/GroupOrchestrationRuntime.ts` | 循环调度：`step()` 一次往返，`run()` 直到 finish |

### 状态机内部决策规则

```typescript
// GroupOrchestrationSupervisor.decide()

收到 ExecutorResult:
  │
  ├── type="init"
  │   → call_supervisor（启动，round=0, skipCallSupervisor=false）
  │
  ├── type="supervisor_decided"
  │   │ 解析 Supervisor LLM 的 tool call 结果:
  │   │
  │   ├── decision="speak"          → instruction: call_agent
  │   ├── decision="broadcast"      → instruction: parallel_call_agents
  │   ├── decision="execute_task"   → instruction: exec_async_task
  │   │   （如果 runInClient=true → exec_client_async_task）
  │   ├── decision="execute_tasks"  → instruction: batch_exec_async_tasks
  │   ├── decision="delegate"       → instruction: delegate
  │   └── decision="finish"         → instruction: finish
  │
  ├── type="agent_spoke" / "agents_broadcasted" / "task_completed"
  │   ├── skipCallSupervisor=true → finish
  │   ├── round >= maxRounds(10)  → finish
  │   └── 否则 → call_supervisor（下一轮，round++）
  │
  └── type="delegated"
      → finish
```

---

## 三、核心运行循环

```
用户发送消息（在 Group 聊天中）
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│  Step 1: call_supervisor                                │
│                                                         │
│  Supervisor Agent 被调用，它拥有以下群组管理工具：       │
│                                                         │
│  speak(agentId, instruction)          → 让某人发言      │
│  broadcast(agentIds, instruction)     → 让多人并行发言   │
│  executeAgentTask(agentId, title,    → 单人异步后台任务  │
│                    task, timeout)                       │
│  executeAgentTasks([{agentId, ...}]) → 多人并行后台任务  │
│  vote(question, options)             → 发起投票         │
│                                                         │
│  Supervisor LLM 分析当前对话，调用其中一个工具            │
│  这个 tool call → 产生 supervisor_decided 事件           │
└──────────┬──────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│  Step 2: 状态机解析 Supervisor 的 tool call              │
│                                                         │
│  GroupOrchestrationSupervisor.decide()                   │
│  读取 decision 字段 → 输出对应的 SupervisorInstruction   │
└──────────┬──────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│  Step 3: Executor 执行指令                               │
│                                                         │
│  call_agent:       调指定 Agent 的 LLM，流式返回         │
│  parallel_call:    并行调多个 Agent                      │
│  exec_async_task:  后台开独立线程执行（独立上下文）        │
│  batch_exec:       并行开多个后台任务                     │
│  delegate:         将控制权完全交给某个 Agent             │
└──────────┬──────────────────────────────────────────────┘
           │
           ▼
     执行完毕，返回 ExecutorResult
     (agent_spoke / agents_broadcasted / task_completed)
           │
           ▼
     状态机判断:
     ├── skipCallSupervisor=true  → finish（本轮结束）
     ├── round >= 10              → finish（达到最大轮次）
     └── 否则                     → 回到 Step 1（下一轮）
```

---

## 四、5 种调度指令

| 指令 | 同步/异步 | 上下文 | 适用场景 |
|------|----------|--------|----------|
| **speak** | 同步 | 共享群聊 | 问题明确匹配某人专长。如 "让前端专家看看这个组件" |
| **broadcast** | 同步并行 | 共享群聊 | 需要多方意见/讨论。如 "大家对微服务架构怎么看？" |
| **executeAgentTask** | 异步 | 独立隔离 | 单人深度工作。如 "写一个完整的 REST API"（超时默认 30 分钟） |
| **executeAgentTasks** | 异步并行 | 各自隔离 | 多人并行工作。如 "同时开发前端+后端+数据库"。同一 Agent 可被派多个任务 |
| **delegate** | 同步 | 移交控制权 | 将整个对话控制权交给某个 Agent |

### 关键区分：意见 vs 研究

| 用户说 | Supervisor 用 | 原因 |
|--------|-------------|------|
| "你怎么看 / 有什么想法 / 给点反馈" | `broadcast` | 基于知识的快速回应 |
| "研究一下 / 深入调查 / 分析一下" | `executeAgentTask` | 需要实际干活（搜索、编码等） |

---

## 五、Supervisor LLM 的决策框架

来自 `packages/builtin-tool-group-management/src/systemRole.ts`：

```
用户请求
    │
    ▼
需要长时间、多步骤的工作吗？
（复杂创作、深度研究、长篇生成）
    │
    ├── YES ──→ 可以多个 Agent 并行吗？
    │              │
    │              ├── YES → executeAgentTasks（并行任务）
    │              │         每个 Agent 独立上下文、异步执行
    │              │
    │              └── NO  → executeAgentTask（单任务）
    │                        独立上下文、异步执行
    │
    └── NO ───→ 需要多个视角/意见吗？
                   │
                   ├── YES → broadcast（并行发言）
                   │         共享群聊上下文、同步返回
                   │
                   └── NO  → speak（单人发言）
                             共享群聊上下文、同步返回
```

---

## 六、6 种工作流模式

来自 `systemRole.ts` 的预定义模式：

### Pattern 1: Discussion（广播讨论）
```
用户: "微服务架构适合这个项目吗？"
Supervisor: broadcast → [架构师, 运维, 后端] 各自给意见
```

### Pattern 2: Sequential Chain（链式发言）
```
用户: "设计一个通知系统"
Supervisor:
  1. speak → 架构师: "提出高层架构"
  2. speak → 后端: "基于架构师的方案，补充实现细节"
  3. speak → 运维: "补充部署和扩缩容考虑"
```

### Pattern 3: Focused（定向提问）
```
用户: "让前端专家回答 React 性能问题"
Supervisor: speak → 前端专家
```

### Pattern 4: Single Async Task（单人异步任务）
```
用户: "写一个完整的用户认证 REST API"
Supervisor: executeAgentTask → 后端
  （独立上下文，异步执行，超时 30 分钟，结果回来后再通知用户）
```

### Pattern 5: Parallel Tasks（并行任务）
```
用户: "同时研究竞争对手 A、B、C"
Supervisor: executeAgentTasks →
  - 研究员: "研究公司A的产品、定价、市场定位"
  - 研究员: "研究公司B的产品、定价、市场定位"  ← 同一 Agent 多个任务
  - 研究员: "研究公司C的产品、定价、市场定位"
```

### Pattern 6: Hybrid（讨论后执行）
```
用户: "帮我做一个数据分析仪表盘"
Supervisor:
  1. broadcast → [设计师, 前端, 数据] 讨论需要什么指标和布局
  2. 达成共识后 → executeAgentTask → 前端: "按讨论需求实现仪表盘"
```

---

## 七、与单 Agent 模式的对比

| | 单 Agent (GeneralChatAgent) | Supervisor 编排 |
|---|---|---|
| **决策者** | LLM 自己决定用什么工具 | Supervisor LLM 决定用哪个 Agent |
| **"工具"** | web_search, crawl_page, sandbox... | speak, broadcast, executeAgentTask... |
| **执行** | 工具返回结果 → LLM 继续下一轮 | Agent 返回结果 → 状态机判断下一轮 |
| **可并行** | 否（串行工具调用） | 是（broadcast / executeAgentTasks） |
| **上下文** | 单个对话线程 | Supervisor + 每个 Agent 有独立上下文 |
| **最大轮次** | maxSteps=15 | maxRounds=10（每轮可能触发多个 Agent） |
| **后台任务** | 无 | executeAgentTask 可在后台异步执行 |

---

## 八、代码路径索引

| 功能 | 文件 |
|------|------|
| 状态机 | `packages/agent-runtime/src/groupOrchestration/GroupOrchestrationSupervisor.ts` |
| 运行时循环 | `packages/agent-runtime/src/groupOrchestration/GroupOrchestrationRuntime.ts` |
| 指令类型定义 | `packages/agent-runtime/src/groupOrchestration/types.ts` |
| Supervisor Agent 的角色定义 | `packages/builtin-agents/src/agents/group-supervisor/systemRole.ts` |
| 群组管理工具的 System Prompt（含 6 种 Pattern） | `packages/builtin-tool-group-management/src/systemRole.ts` |
| 前端编排循环 | `src/store/chat/slices/aiAgent/actions/groupOrchestration.ts` |
| 群组聊天页面路由 | `src/routes/(main)/group/_layout/index.tsx` |
| 群组聊天输入框 | `src/routes/(main)/group/features/Conversation/MainChatInput/GroupChat.tsx` |
