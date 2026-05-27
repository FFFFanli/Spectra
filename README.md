# Spectra — AI 智能数据分析与多 Agent 协作平台

基于 `FastAPI + LangGraph + DuckDB + Vue 3` 的 AI 数据分析应用，同时支持 **Solo（单 Agent + 工具循环）** 与 **Team MTC（统一执行体 + 自动 Plan + 并行调度）** 两种工作模式，提供联网搜索、代码沙盒、数据分析、报告导出与定时巡检能力。

---

## Agent 架构

Spectra 提供两条独立的 Agent 链路，前端会根据用户在 ChatView 中的模式选择路由到对应后端端点：

| 模式 | 入口端点 | 实现 | 适用场景 |
|---|---|---|---|
| **Solo** | `POST /api/chat` | `backend/agent/single_agent.py`（LangGraph StateGraph，LLM ↔ Tool 自主循环） | 单轮到中等复杂度的对话、即席分析、问答 |
| **Team MTC** | `POST /api/v2/chat` | `backend/agent/v2/mtc/runtime.py`（统一执行体 + Plan_Manager + 并行 Scheduler + Skill Workflow） | 长链条任务、多文件处理、复杂报告产出 |

> Team 模式默认走 MTC 实现；通过环境变量 `SPECTRA_TEAM_MTC_ENABLED=0` 可回退到旧版 `legacy_runtime.py`（多 Agent Supervisor 状态机），用于灰度回滚。

### 共同基础设施

- **LLM 工厂**（`backend/agent/v2/llm.py`）：DashScope (Qwen) / OpenAI (GPT-4o) / DeepSeek (V4) 三套 provider 热切换，自研 DeepSeek V4 适配层处理 reasoning_content 流式与孤儿工具调用修复
- **Executor → Validator → Fixer 自检循环**（`backend/agent/v2/infra/`）：代码执行结果自动校验，失败时按错误类别生成修复代码，最多 3 次重试
- **流中断容错**：针对 httpx / anyio / OpenAI SDK 的常见中断异常内置重试
- **请求级隔离**：基于 Python ContextVar 实现模型选择、用量统计、产物收集与表权限范围（`table_scope`）的并发安全

### Solo 模式特性

- LangGraph 条件路由 `call_llm → call_tools → call_llm`，步数上限 40，接近上限时自动触发 force_summarize 兜底
- 完整工具面板，全部 12 类工具均可调用
- SSE 事件：`llm_stream` / `reasoning_stream` / `tool_start` / `tool_result` / `artifacts` / `file` / `usage` / `done` / `error`

### Team MTC 模式特性（对标 Trae SOLO MTC）

- **File_Parser**：自动解析 PDF / PPTX / DOCX / 图片 / 音视频 / JSON 上传文件，注入 LLM 上下文
- **Plan_Manager**：LLM 强制先调 `make_plan` 拆解任务为 ≤30 步带依赖图的执行计划；运行中可 `update_plan` / `add_step` / `revise_plan`
- **PlanScheduler**：依赖图拓扑序调度，最大并发 4，单步失败 ≤3 次重试，超限触发自动 replan
- **Member Agents**：Coder / Researcher / Writer / Designer / Reviewer / Responder 6 类执行成员，由 Plan 步骤的 `assignee_agent_id` 动态调度
- **Skill_Workflow**：5 套预置 YAML 工作流模板（数据报告 / 竞品分析 / 会议纪要 / 活动方案 / 产品 PRD）
- **Background_Task_Manager**：长耗时任务后台异步执行，结果通过 SSE `task_completed` 事件回推
- **持久化**：Plan / Step / Artifact / BackgroundTask 全部落 SQLite，支持崩溃后恢复

---

## 功能一览

- 上传 CSV / Excel 自动入库 DuckDB；支持 PDF / PPTX / DOCX / 图片 / 音视频 / JSON 落盘并解析
- 自动数据画像与图表生成（Plotly 交互式）
- **联网搜索**：DuckDuckGo + Google + Bing RSS 多引擎 fallback；Jina AI 网页爬取 + 本地 urllib 回退
- **代码执行**：E2B 远程沙盒 + 本地 subprocess 安全扫描双引擎，失败自动诊断 + 修复
- **12 类工具**：搜索、爬取、计算器、图表生成、代码沙盒、DuckDB 查询、重型文件处理、文档导出、GTD 任务管理、知识库检索、用户记忆、定时任务、用户交互
- **定时巡检**（APScheduler + Cron），结果持久化 SQLite
- **对话记忆**：ChromaDB 结构化向量检索（preference / fact / experience / context）+ SQLite 对话历史
- **报告导出**：Markdown → DOCX / PDF，支持图表 PNG 嵌入与 CJK 字体适配
- SSE 流式通信，实时打字机效果，推理链与工具调用过程可视化

---

## 目录结构

```text
Spectra/
├── backend/
│   ├── agent/
│   │   ├── single_agent.py             # Solo Agent (LLM ↔ Tool 循环) → /api/chat
│   │   ├── graph_agent.py              # 图 Agent (DAG 多节点流水线，工作流模板)
│   │   ├── prompts.py                  # 系统提示词
│   │   ├── plan_state.py               # Plan 状态结构
│   │   └── v2/
│   │       ├── llm.py                  # LLM 工厂 (DashScope / OpenAI / DeepSeek)
│   │       ├── legacy_runtime.py       # 旧 Team Supervisor 状态机 (灰度回退)
│   │       ├── planner.py / state.py   # 旧版 Supervisor 决策与状态
│   │       ├── infra/                  # Executor / Validator / Fixer / Skills
│   │       ├── members/                # 6 类成员 Agent (coder/writer/researcher/responder/designer/reviewer)
│   │       ├── prompts/                # 各成员 System Prompt
│   │       ├── workflows/              # 5 个 Skill Workflow YAML 模板
│   │       └── mtc/                    # Team MTC 主实现 → /api/v2/chat
│   │           ├── runtime.py          # 主循环：File_Parser → make_plan → Scheduler → Reply
│   │           ├── plan_manager.py     # Plan 生命周期 (make/update/add/revise)
│   │           ├── plan_tools.py       # LLM 工具定义
│   │           ├── scheduler.py        # 依赖图调度，max_concurrency=4
│   │           ├── file_parser.py      # 多格式文件解析
│   │           ├── background_tasks.py # 后台异步任务
│   │           ├── sse_translator.py   # 内部事件 → SSE 翻译
│   │           ├── context_manager.py  # 上下文压缩
│   │           ├── persistence.py      # SQLite 持久化
│   │           └── workflow_loader.py  # YAML 工作流加载
│   ├── tools/                          # 12 类 LangChain 工具
│   │   ├── web_search.py               # 联网搜索 + 网页爬取
│   │   ├── calculator.py               # 安全数学求值 + 描述性统计
│   │   ├── visualization.py            # Plotly 图表生成
│   │   ├── sandbox.py                  # E2B 远程沙盒 / 本地子进程
│   │   ├── duckdb_tools.py             # DuckDB 查询与内省（含 table_scope 权限控制）
│   │   ├── heavy_tools.py              # run_in_sandbox + 自动校验
│   │   ├── export_conversation.py      # Markdown → DOCX/PDF
│   │   ├── task_manager.py             # GTD 任务管理 (持久化)
│   │   ├── knowledge_base.py           # ChromaDB 知识库检索
│   │   ├── user_memory.py              # 用户记忆 CRUD
│   │   ├── cron_manager.py             # 定时任务管理
│   │   └── user_interaction.py         # ask_user / request_confirmation
│   ├── api.py                          # FastAPI 路由 (~20 个端点)
│   ├── db_utils.py                     # DuckDB 数据管理 (导入/查询/画像/外部数据库联邦)
│   ├── search_service.py               # 纯 stdlib 搜索+爬取引擎
│   ├── report_generator.py             # Markdown → DOCX/PDF/HTML 报告生成
│   ├── memory.py                       # ChromaDB 结构化向量记忆
│   ├── conversation_store.py           # SQLite 对话历史持久化
│   ├── state_store.py                  # SQLite 任务与预警持久化
│   ├── checkpoint_store.py             # LangGraph 状态检查点 (SQLite)
│   ├── request_context.py              # ContextVar 请求级隔离
│   ├── prompt_loader.py                # System Prompt 组装
│   ├── skill_loader.py                 # Skill 动态加载
│   ├── local_exec_runner.py            # 本地子进程代码执行器 (安全扫描)
│   └── app_paths.py                    # 路径配置
├── frontend/                           # Vite + Vue 3 应用
│   ├── src/
│   │   ├── App.vue
│   │   ├── store.js                    # 单例响应式 Store
│   │   ├── components/                 # ChatView / SoloChatView / TeamChatView / Sidebar / ContextPanel...
│   │   ├── composables/                # useChat / useHistory / useSettings / usePreferences
│   │   └── utils/                      # charts.js / sse.js / crypto.js
│   ├── index.html
│   ├── vite.config.js                  # Vite 配置 (代理 /api → :8000)
│   └── package.json
├── data/                               # DuckDB / SQLite 等运行期数据
├── artifacts/                          # 图表 HTML/PNG、报告、导出文件
├── chroma_db/                          # ChromaDB 向量记忆与知识库
└── tests/                              # 单元测试
```

---

## 环境要求

- Python 3.11+
- Node.js 18+（前端开发模式）
- Windows / macOS / Linux

---

## 安装与启动

```bash
# 后端
pip install -r requirements.txt
copy .env.example .env   # 编辑填入 API Key

# 前端 (开发模式)
cd frontend && npm install && npm run dev   # Vite :5173，代理 /api → :8000

# 前端 (生产构建)
cd frontend && npm run build                 # 输出到 frontend/dist/
```

### 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | 否 | 通义千问 API Key |
| `OPENAI_API_KEY` | 否 | OpenAI API Key |
| `DEEPSEEK_API_KEY` | 否 | DeepSeek API Key |
| `E2B_API_KEY` | 否 | E2B 沙盒 Key（未配置时回退本地子进程） |
| `SPECTRA_ACCESS_CODE` | 否 | 访问密码（不设则无鉴权） |
| `SPECTRA_TEAM_MTC_ENABLED` | 否 | `1`（默认）走 Team MTC，`0` 回退旧 legacy_runtime |

### 启动后端

```bash
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问 [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## API 端点

### 数据管理

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/upload` | 文件上传（CSV/Excel → DuckDB；PDF/PPTX/DOCX/图片/音视频/JSON → artifacts） |
| POST | `/api/connect_db` | 外部数据库直连（MySQL/PostgreSQL via DuckDB ATTACH） |
| GET | `/api/tables` | 获取所有用户表 |
| GET | `/api/table_data/{table_name}` | 获取表数据预览 |
| POST | `/api/profile` | 自动数据画像报告 |

### Agent 对话

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/chat` | Solo Agent SSE 端点（单 Agent + 完整工具面板） |
| POST | `/api/v2/chat` | Team MTC SSE 端点（统一执行体 + Plan + 并行调度） |

SSE 事件类型：`llm_stream`, `reasoning_stream`, `tool_start`, `tool_result`, `artifacts`, `file`, `usage`, `user_question`, `done`, `error`，Team MTC 额外发送 `file_parsed`, `plan_created`, `plan_updated`, `step_started`, `step_completed`, `step_failed`, `task_completed`, `reply`。

### Team MTC 辅助查询

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/api/v2/workflows` | 列出所有 Skill_Workflow 模板 |
| GET | `/api/v2/plan/{thread_id}` | 获取指定线程的最新 Plan 快照与产物列表 |
| GET | `/api/v2/tasks?thread_id=...` | 获取后台任务状态 |

### 对话历史

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/api/conversations` | 对话列表 |
| GET | `/api/conversations/{id}` | 获取单条对话 |
| POST | `/api/conversations/{id}` | 保存对话 |
| DELETE | `/api/conversations/{id}` | 删除单条 |
| DELETE | `/api/conversations` | 清空全部 |

### 报告导出

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/export_conversation` | 导出 DOCX / PDF 报告 |

### 定时调度

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/schedule` | 创建定时巡检任务（Cron） |
| GET | `/api/alerts` | 获取巡检预警记录 |

### 配置

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/settings` | 更新 API Keys 与模型选择 |
| GET | `/api/models` | 获取可用模型列表 |
| GET | `/api/workflows` | 列出工作流模板（精简后） |

---

## 工具面板（12 类）

| 类别 | 工具 | 说明 |
|---|---|---|
| 联网搜索 | `web_search` | DuckDuckGo / Google / Bing RSS 多引擎 fallback |
| 网页爬取 | `crawl_page` | Jina AI 全文爬取 + 本地 urllib 回退 |
| 搜索+爬取 | `search_and_crawl` | 搜索并爬取前 N 篇全文 |
| 计算器 | `calculator` | 安全数学表达式求值 |
| 描述性统计 | `summarize_numbers` | 计数/总和/均值/中位数/标准差 |
| 图表生成 | `generate_chart` | Plotly 交互式图表（HTML + PNG） |
| 沙盒执行 | `execute_python` / `run_in_sandbox` | E2B 远程执行 + 本地安全扫描回退 |
| DuckDB 查询 | `list_tables` / `query_duckdb` | SQL 查询、表内省，受 `table_scope` 权限控制 |
| 重型处理 | `heavy_data_processing` | 大文件转换与批量处理 |
| 文档导出 | `generate_docx` | Markdown → DOCX/PDF 报告 |
| 任务管理 | `create_task` 等 | GTD 风格任务 CRUD（持久化） |
| 知识库 | `search_knowledge` | ChromaDB 语义检索 |
| 用户记忆 | `save_memory` 等 | 偏好/事实/经验/上下文长期记忆 |
| 定时任务 | `schedule_cron` | Cron 定时任务管理 |
| 用户交互 | `ask_user` / `request_confirmation` | 向用户提问或请求确认 |

---

## E2B 沙盒说明

- 配置 `E2B_API_KEY` 后，LLM 生成的代码优先在 E2B 远程沙盒执行
- 未配置时自动回退到本地子进程执行（`local_exec_runner.py`，含危险导入拦截与代码安全扫描）
- 沙盒会按需挂载 `data/data.duckdb` 与 `backend/search_service.py`，让生成代码可直接查询数据
- 生产环境建议配置 E2B 以获得更强的隔离性

---

## 运行期文件

| 路径 | 说明 |
|---|---|
| `data/data.duckdb` | 主数据仓库（DuckDB） |
| `data/app_state.db` | 任务与预警持久化（SQLite） |
| `data/checkpoints.db` | LangGraph 状态检查点（SQLite） |
| `artifacts/` | 图表 HTML/PNG、报告、导出文件 |
| `chroma_db/` | ChromaDB 向量记忆与知识库 |

---

## 运行测试

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## 架构要点

1. **双链路 Agent**：Solo（单 Agent 自主循环）与 Team MTC（统一执行体 + Plan 调度）共享底层工具与 LLM 工厂，互不干扰
2. **多引擎 Fallback**：搜索 DuckDuckGo → Google → Bing RSS；爬取 Jina AI → 本地 urllib；沙盒 E2B → 本地 subprocess
3. **请求级隔离**：基于 Python ContextVar 实现模型选择、用量统计、表权限范围、产物收集的线程/协程安全
4. **持久化多层**：DuckDB（数据）+ SQLite（对话/任务/检查点/Plan）+ ChromaDB（向量记忆）+ 文件系统（产物）
5. **SSE 事件标准化**：前端统一 dispatch 处理流式与状态事件，Team MTC 额外推送 Plan / Step / Task 状态变化
6. **灰度回退**：Team 模式可通过 `SPECTRA_TEAM_MTC_ENABLED=0` 切回旧 Supervisor 实现
