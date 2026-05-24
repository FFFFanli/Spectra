# LangGraph 多 Agent 数据分析报告系统

基于 `FastAPI + LangGraph + DuckDB + Vue 3` 的多智能体数据分析应用，支持三种 Agent 协作模式、联网搜索、自动化工作流和定时巡检。

---

## 三种 Agent 模式

| 模式 | 后端入口 | API 端点 | 说明 |
|---|---|---|---|
| **Solo 单 Agent** | `backend/agent/single_agent.py` | `POST /api/agent/chat` | LLM ↔ Tool 自主循环，Agent 自己决定何时调用工具 |
| **Team Supervisor (v2)** | `backend/agent/v2/runtime.py` | `POST /api/chat` | Supervisor + Coder/Writer/Researcher/Responder 多成员协作，executor → validator → fixer 三段式自检循环 |
| **Graph 图 Agent** | `backend/agent/graph_agent.py` | `POST /api/graph/stream` | 动态 DAG 多节点流水线，每个节点是独立 Subgraph |

前端默认走"自动模式"：根据是否有上传文件 / 外部数据库 / 数据分析意图，在 Solo 与 Team 之间自动切换；用户也可在输入框模式选择器里手动锁定。

---

## 功能一览

- 上传 CSV / Excel 到 DuckDB，自动解析入库
- 自动数据体检与图表生成
- Team Supervisor v2：Coder / Writer / Researcher / Responder 多成员协作 + executor → validator → fixer 自检循环
- Human-in-the-loop 代码确认与自动修复回路
- **联网搜索**：DuckDuckGo + Jina AI 多源 fallback
- **5 套预定义自动化工作流**：AI 新闻日报、竞品监控、每周巡检、股价告警、安全漏洞日报
- **工具生态**：搜索、爬取、计算器、图表生成、远程沙盒执行
- 定时巡检预警（APScheduler + Cron）
- SSE 流式通信，实时打字机效果
- 对话记忆持久化（ChromaDB 向量检索 + SQLite）
- 历史对话管理（LocalStorage，按时间分组）

---

## 目录结构

```text
project/
├── backend/
│   ├── agent/                      # Agent 引擎
│   │   ├── single_agent.py         # Solo 单 Agent (LLM ↔ Tool 循环)
│   │   ├── graph_agent.py          # 图 Agent (动态 DAG + 5 套预定义工作流)
│   │   └── v2/                     # Team Supervisor v2 (runtime / planner / members / infra)
│   ├── tools/                      # LangChain Tool 工具包 (7 个工具)
│   │   ├── web_search.py           # 联网搜索 + 网页爬取 (3 个工具)
│   │   ├── calculator.py           # 安全数学表达式求值 + 描述性统计 (2 个工具)
│   │   ├── visualization.py        # 智能图表生成 (1 个工具)
│   │   └── sandbox.py              # E2B 远程沙盒 / 本地回退执行 (1 个工具)
│   ├── api.py                      # FastAPI 路由 (20+ 端点)
│   ├── db_utils.py                 # DuckDB 数据管理
│   ├── search_service.py           # 纯 stdlib 搜索+爬取引擎
│   ├── skill_registry.py           # Skill 注册与动态检索
│   ├── state_store.py              # SQLite 任务与预警持久化
│   ├── memory.py                   # ChromaDB 向量记忆检索
│   ├── pdf_autofill_engine.py      # PDF 自动填充
│   ├── report_templates.py         # 报告模板
│   ├── local_exec_runner.py        # 本地子进程代码执行器
│   └── app_paths.py                # 路径配置
├── frontend/
│   ├── index.html                  # 单文件 Vue 3 应用
│   └── static/                     # CDN 静态资源
├── data/                           # DuckDB、SQLite 等运行期数据
├── artifacts/                      # 图表 HTML/PNG、报告、导出文件
└── tests/                          # 测试脚本
```

---

## 环境要求

- Python 3.11+
- Windows / macOS / Linux

## 安装依赖

```bash
pip install -r requirements.txt
```

## 环境变量

复制环境模板：

```bash
copy .env.example .env
```

关键变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `DASHSCOPE_API_KEY` | ✅ | Qwen / DashScope API Key |
| `E2B_API_KEY` | 否 | E2B 沙盒执行 Key（未配置时回退到本地执行） |
| `TASK_TTL_SECONDS` | 否 | 任务状态保留时长，默认 `86400` |
| `MAX_TASKS` | 否 | 最大任务保留数，默认 `500` |
| `MAX_ALERTS` | 否 | 最大预警保留数，默认 `200` |

---

## 启动项目

```bash
# 直接启动 (端口 8000，入口在 api.py 底部)
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000

# 带热重载 (开发模式)
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：[http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## API 端点一览

### 数据管理

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/upload` | 文件上传 (CSV/Excel → DuckDB) |
| POST | `/api/connect_db` | 外部数据库直连 (MySQL/PostgreSQL) |
| GET | `/api/tables` | 获取所有用户表 |
| GET | `/api/table_data/{table_name}` | 获取表数据预览 |
| POST | `/api/profile` | 自动数据体检报告 |

### Agent 对话 (SSE 流式)

| 方法 | 路由 | 模式 | 事件类型 |
|---|---|---|---|
| POST | `/api/agent/chat` | Solo 单 Agent | `llm_stream`, `tool_start`, `tool_result`, `done`, `error` |
| POST | `/api/chat` | Team Supervisor (v2) | `node`, `runtime`, `message`, `chart`, `file`, `report`, `done`, `error` 等 |
| POST | `/api/graph/stream` | 图 Agent 模式 | `llm_stream`, `tool_start`, `tool_result`, `done` |

### 工作流

| 方法 | 路由 | 说明 |
|---|---|---|
| GET | `/api/workflows` | 列出所有预定义工作流模板 |

### 定时调度

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/schedule` | 创建定时巡检任务 (Cron) |
| GET | `/api/alerts` | 获取巡检预警记录 |

### 其他

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/settings` | 更新 API Keys 配置 |
| POST | `/api/chat_json` | JSON 阻塞模式（后台异步 + 轮询） |
| POST | `/api/resume_json` | JSON 恢复模式 |
| GET | `/api/task_status/{task_id}` | 任务状态轮询 |

---

## 预定义工作流模板

在自动化面板可一键启动：

| 工作流 ID | 名称 | 流水线 |
|---|---|---|
| `ai_news_daily` | 每日 AI 新闻抓取 | 搜索 → 趋势分析 → 日报生成 |
| `competitor_monitor` | 竞品数据监控日报 | 竞品搜索 → 策略分析 → 监控报告 |
| `weekly_competitor_scan` | 每周竞品动态巡检 | 产品搜索 + 舆情搜索 → 综合分析 |
| `stock_alert` | 股价/大盘异常告警 | 行情搜索 → 异常检测告警 |
| `security_vuln_daily` | 安全漏洞日报 | 漏洞搜索 → 风险评估报告 |

---

## Agent 工具生态 (7 个工具)

| 工具 | 函数名 | 说明 |
|---|---|---|
| 联网搜索 | `web_search` | DuckDuckGo 搜索，返回 XML 格式结果 |
| 网页爬取 | `crawl_page` | Jina AI 爬取全文（最高 8000 字符） |
| 搜索+爬取 | `search_and_crawl_tool` | 搜索并爬取前 N 篇全文 |
| 计算器 | `calculator` | 安全数学表达式求值（算术/三角/对数/统计） |
| 描述性统计 | `summarize_numbers` | 计数/总和/均值/中位数/标准差 |
| 图表生成 | `generate_chart` | 根据 JSON/CSV 数据智能生成 Plotly 图表 |
| 沙盒执行 | `execute_python` | E2B 远程执行 Python 代码，自动回退本地 |

---

## 前端视图

| 视图 | 说明 |
|---|---|
| 聊天 (Chat) | 默认视图，对话 + 右侧 Agent Runtime 工作台 |
| 自动化 (Automation) | 任务模板、定时配置、执行历史 |
| 数据集/数据库 (Database) | 外部数据库直连配置 |
| 系统设置 (Settings) | API Keys 配置 |

聊天视图底部工具栏：上传按钮 / 停止按钮（加载中自动切换）、模式切换（Solo / Team）、模型选择。

---

## 运行测试

```bash
# 单元测试
python -m unittest discover -s tests -p "test_*.py" -v

# 新增端点集成测试 (需先启动服务)
$env:PYTHONIOENCODING='utf-8'; python tests/test_new_endpoints.py
```

覆盖范围：

- `backend.db_utils.save_file_to_duckdb()`
- `backend.db_utils.get_database_schema()`
- `backend.agent.v2.infra.executor_impl.executor_node()`
- `backend.agent.graph_agent` — 图 Agent 动态 DAG 构建
- 全部 7 个 LangChain Tool 的导入与定义

---

## 运行期文件

| 路径 | 说明 |
|---|---|
| `data/data.duckdb` | 主数据仓库（DuckDB） |
| `data/app_state.db` | 任务与预警持久化（SQLite） |
| `data/runs/` | 每次代码执行的独立工作目录 |
| `artifacts/` | 图表 HTML/PNG、清洗后 Excel、Word/PDF 报告 |
| `chroma_db/` | ChromaDB 向量记忆数据 |

---

## E2B 沙盒说明

- 配置 `E2B_API_KEY` 后，LLM 生成的代码优先在 E2B 远程沙盒执行
- 未配置时自动回退到本地子进程执行（仅适合开发环境）
- 生产环境建议强制沙盒执行

---

## 架构要点

1. **模式由场景决定**：单 Agent 用于日常对话和工具调用，图 Agent 用于固定流程的深度研究，群组编排用于多角色协作
2. **Phase 状态驱动**：`state.phase`（`user_input` / `llm_result` / `tool_result`）显式决定流转
3. **多引擎 Fallback**：搜索 DuckDuckGo → Google，爬取 Jina AI → 本地 urllib
4. **SSE 事件标准化**：前端统一处理 `llm_stream`、`tool_start`、`tool_result`、`done`、`error`
5. **Checkpointer 持久化**：LangGraph `MemorySaver`（开发）/ `SqliteSaver`（生产），支持中断恢复和 Human-in-the-loop
