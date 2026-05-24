# Spectra — AI 智能数据分析平台

基于 `FastAPI + LangGraph + DuckDB + Vue 3` 的单 Agent 数据分析应用，支持 LLM 自主工具调用、联网搜索、代码执行、数据分析和定时巡检。

---

## Agent 架构

采用 LangGraph StateGraph 实现 **LLM ↔ Tool 自主循环**：Agent 接收用户消息后自主决定调用哪些工具、何时停止，通过条件路由在 call_llm → call_tools → call_llm 之间循环直至任务完成。步数接近上限时自动触发 force_summarize 兜底，确保不返回空白消息。

- 入口：`backend/agent/single_agent.py` → `POST /api/chat`（SSE 流式）
- 自研 DeepSeek V4 适配层，处理 reasoning_content 流式传输和孤儿工具调用修复
- Validator-Fixer 自动修复循环：代码执行失败时自动诊断错误类型并生成修复代码
- 支持 DashScope (Qwen) / OpenAI (GPT-4o) / DeepSeek (V4) 三套模型热切换

---

## 功能一览

- 上传 CSV / Excel 到 DuckDB，自动解析入库
- 自动数据画像与图表生成（Plotly / ECharts）
- **联网搜索**：DuckDuckGo + Google + Bing RSS 多引擎 fallback，Jina AI 网页爬取
- **代码执行**：E2B 远程沙盒 + 本地 subprocess 安全扫描双引擎
- **12 类工具**：搜索、爬取、计算器、图表生成、代码沙盒、DuckDB 查询、文件处理、文档导出、GTD 任务管理、知识库检索、用户记忆、定时任务
- **定时巡检**（APScheduler + Cron），结果持久化到 SQLite
- **对话记忆**：ChromaDB 向量检索 + SQLite 对话历史持久化
- **报告导出**：Markdown → DOCX / PDF，支持图表嵌入与 CJK 字体适配
- SSE 流式通信，实时打字机效果，推理链与工具调用过程可视化

---

## 目录结构

```text
project/
├── backend/
│   ├── agent/
│   │   ├── single_agent.py          # Solo Agent (LLM ↔ Tool 循环)
│   │   ├── graph_agent.py           # 图 Agent (DAG 多节点流水线，预留)
│   │   ├── prompts.py               # 系统提示词
│   │   ├── plan_state.py            # 计划状态管理
│   │   └── v2/
│   │       ├── llm.py               # LLM 工厂 (DeepSeekV4ChatOpenAI 适配层)
│   │       └── infra/
│   │           ├── executor_impl.py  # 代码执行器 (Validator-Fixer 自动修复)
│   │           ├── validator.py     # 执行结果校验与错误分类
│   │           └── skills.py        # Skill 定义
│   ├── tools/                       # 12 类 LangChain 工具
│   │   ├── web_search.py            # 联网搜索 + 网页爬取
│   │   ├── calculator.py            # 安全数学表达式求值 + 描述性统计
│   │   ├── visualization.py         # Plotly 图表生成
│   │   ├── sandbox.py               # E2B 远程沙盒 / 本地回退执行
│   │   ├── duckdb_tools.py          # DuckDB 查询与内省
│   │   ├── heavy_tools.py           # 文件转换与重型处理
│   │   ├── export_conversation.py   # DOCX 导出
│   │   ├── task_manager.py          # GTD 任务管理 (持久化)
│   │   ├── knowledge_base.py        # ChromaDB 知识库检索
│   │   ├── user_memory.py           # 用户记忆存储与检索
│   │   ├── cron_manager.py          # 定时任务管理
│   │   └── user_interaction.py      # 用户交互 (ask_user, request_confirmation)
│   ├── api.py                       # FastAPI 路由 (16 个端点)
│   ├── db_utils.py                  # DuckDB 数据管理 (导入/查询/画像/外部数据库联邦)
│   ├── search_service.py            # 纯 stdlib 搜索+爬取引擎
│   ├── report_generator.py          # Markdown → DOCX/PDF 报告生成
│   ├── memory.py                    # ChromaDB 向量记忆
│   ├── conversation_store.py        # SQLite 对话历史持久化
│   ├── state_store.py               # SQLite 任务与预警持久化
│   ├── checkpoint_store.py          # LangGraph 状态检查点 (SQLite)
│   ├── request_context.py           # ContextVar 请求级隔离
│   ├── skill_loader.py              # Skill 动态加载
│   ├── local_exec_runner.py         # 本地子进程代码执行器 (安全扫描)
│   └── app_paths.py                 # 路径配置
├── frontend/
│   ├── src/
│   │   ├── App.vue                  # 根组件
│   │   ├── store.js                 # 单例响应式 Store
│   │   ├── components/              # ChatView, ChatMessage, Sidebar, ContextPanel 等
│   │   ├── composables/             # useChat, useHistory, useSettings, usePreferences
│   │   └── utils/                   # charts.js, sse.js, crypto.js
│   ├── index.html                   # Vite 入口
│   ├── vite.config.js               # Vite 配置 (代理 /api → :8000)
│   └── package.json
├── data/                            # DuckDB、SQLite 等运行期数据
├── artifacts/                       # 图表 HTML/PNG、报告、导出文件
└── tests/                           # 测试脚本
```

---

## 环境要求

- Python 3.11+
- Node.js 18+ (前端开发)
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
| `E2B_API_KEY` | 否 | E2B 沙盒 Key（未配置时回退本地执行） |
| `SPECTRA_ACCESS_CODE` | 否 | 访问密码（不设则无鉴权） |

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
| POST | `/api/upload` | 文件上传 (CSV/Excel → DuckDB, PDF/JSON → artifacts) |
| POST | `/api/connect_db` | 外部数据库直连 (MySQL/PostgreSQL via DuckDB ATTACH) |
| GET | `/api/tables` | 获取所有用户表 |
| GET | `/api/table_data/{table_name}` | 获取表数据预览 |
| POST | `/api/profile` | 自动数据画像报告 |

### Agent 对话

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/chat` | 统一 SSE 流式对话端点（Solo Agent + 全工具面板） |

SSE 事件类型：`llm_stream`, `reasoning_stream`, `tool_start`, `tool_result`, `artifacts`, `file`, `usage`, `done`, `error`

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
| POST | `/api/schedule` | 创建定时巡检任务 (Cron) |
| GET | `/api/alerts` | 获取巡检预警记录 |

### 配置

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/settings` | 更新 API Keys 与模型选择 |
| GET | `/api/models` | 获取可用模型列表 |
| GET | `/api/workflows` | 工作流模板列表 |

---

## 工具面板（12 类）

| 类别 | 工具 | 说明 |
|---|---|---|
| 联网搜索 | `web_search` | DuckDuckGo / Google / Bing RSS 多引擎 fallback |
| 网页爬取 | `crawl_page` | Jina AI 全文爬取 + 本地 urllib 回退 |
| 搜索+爬取 | `search_and_crawl` | 搜索并爬取前 N 篇全文 |
| 计算器 | `calculator` | 安全数学表达式求值 |
| 描述性统计 | `summarize_numbers` | 计数/总和/均值/中位数/标准差 |
| 图表生成 | `generate_chart` | Plotly 交互式图表 (HTML + PNG) |
| 沙盒执行 | `execute_python` | E2B 远程执行 + 本地安全扫描回退 |
| DuckDB 查询 | `query_duckdb` 等 | SQL 查询、表内省、Schema 浏览 |
| 重型处理 | `heavy_data_processing` | 大文件转换与批量处理 |
| 文档导出 | `generate_docx` | Markdown → DOCX/PDF 报告 |
| 任务管理 | `create_task` 等 | GTD 风格任务 CRUD |
| 知识库 | `search_knowledge` | ChromaDB 语义检索 |
| 用户记忆 | `save_memory` 等 | 偏好/事实/经验长期记忆 |
| 定时任务 | `schedule_cron` | Cron 定时任务管理 |
| 用户交互 | `ask_user` | 向用户提问或请求确认 |

---

## E2B 沙盒说明

- 配置 `E2B_API_KEY` 后，LLM 生成的代码优先在 E2B 远程沙盒执行
- 未配置时自动回退到本地子进程执行（`local_exec_runner.py`，含危险导入拦截与代码安全扫描）
- 生产环境建议配置 E2B 以保证隔离性

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

1. **单 Agent 自主循环**：基于 LangGraph StateGraph，LLM 自主决策工具调用，通过条件路由实现 call_llm ↔ call_tools 循环
2. **流中断容错**：针对 httpx / anyio / OpenAI SDK 的常见中断异常内置重试机制
3. **多引擎 Fallback**：搜索 DuckDuckGo → Google → Bing RSS，爬取 Jina AI → 本地 urllib，沙盒 E2B → 本地 subprocess
4. **请求级隔离**：基于 Python ContextVar 实现模型选择、用量统计、产物收集的线程/协程安全
5. **持久化多层**：DuckDB (数据) + SQLite (对话/任务/检查点) + ChromaDB (向量记忆) + 文件系统 (产物)
6. **SSE 事件标准化**：前端统一 dispatch 处理 `llm_stream`、`tool_start`、`tool_result`、`done`、`error` 等事件
