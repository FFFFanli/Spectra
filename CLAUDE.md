# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Spectra is an AI data analysis platform built with **FastAPI + LangGraph + DuckDB + Vue 3**. It exposes two parallel agent runtimes (**Solo** for single-agent + tool loop, **Team MTC** for unified-executor + auto-plan + parallel scheduling), web search, code sandbox, automated workflows, and scheduled monitoring.

## Commands

```bash
# Backend
pip install -r requirements.txt          # Install Python dependencies
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload  # Dev server

# Frontend
cd frontend && npm install && npm run dev   # Vite dev server on :5173, proxies /api to :8000
cd frontend && npm run build                # Production build → frontend/dist/

# Tests
python -m unittest discover -s tests -p "test_*.py" -v   # Run all tests
python -m unittest tests.test_db_utils.DbUtilsTests       # Run a single test class
python -m unittest tests.test_db_utils.DbUtilsTests.test_save_csv_to_duckdb_sanitizes_columns  # Run single test

# Type checking (if mypy installed)
mypy backend/
```

## Architecture

### Agent Runtimes (2 active modes, frontend routes by `agentMode`)

| Mode | Endpoint | File | Description |
|------|----------|------|-------------|
| **Solo** | `POST /api/chat` | `backend/agent/single_agent.py` | Single LLM ↔ Tool loop via LangGraph `StateGraph`. LLM autonomously chooses tool calls; recursion limit 100, step limit 40, force_summarize fallback near limit. |
| **Team MTC** | `POST /api/v2/chat` | `backend/agent/v2/mtc/runtime.py` | Unified executor with auto Plan generation, dependency-graph scheduler (max concurrency 4), member dispatch, and Skill_Workflow templates. Primary Team implementation. |
| _Team legacy_ | `POST /api/v2/chat` (when `SPECTRA_TEAM_MTC_ENABLED=0`) | `backend/agent/v2/legacy_runtime.py` | Old Supervisor + multi-member state machine. Kept for gradual rollout / rollback. |
| _Graph Agent_ | _(internal helper)_ | `backend/agent/graph_agent.py` | Dynamic DAG pipeline where each node is an independent subgraph; used by predefined workflow templates. |

Frontend selects mode via `store.agentMode` and `useChat.js` posts to `/api/chat` or `/api/v2/chat` accordingly.

### Team MTC Internals (`backend/agent/v2/mtc/`)

The MTC runtime is the most important code path for Team mode:

```
runtime.py          # TeamMTCRuntime — main loop: File_Parser → make_plan → Scheduler → Reviewer → Responder
plan_manager.py     # Plan / PlanStep dataclasses, lifecycle (MAX_STEPS=30, MAX_STEP_RETRIES=3)
plan_tools.py       # LLM tool defs: make_plan / update_plan / add_step / revise_plan / finish
scheduler.py        # Dependency-graph topological scheduler with asyncio.gather, MAX_CONCURRENCY=4
file_parser.py      # PDF / PPTX / DOCX / image / audio / video / JSON / text parsing
background_tasks.py # Long-running task offload with SSE task_completed event
sse_translator.py   # Internal events → SSE event translator
context_manager.py  # Conversation context compression
persistence.py      # SQLite persistence for Plan / Step / Artifact / BackgroundTask
workflow_loader.py  # Loads YAML templates from backend/agent/v2/workflows/
```

Member agents live in `backend/agent/v2/members/` (6 roles: `coder`, `writer`, `researcher`, `responder`, `designer`, `reviewer`). Each member exposes an `execute(ctx)` interface and is selected via `PlanStep.assignee_agent_id`.

Key MTC design principles:
- Plan is the single source of truth — every LLM tool call mutates the Plan, never the conversation messages directly.
- Scheduler is independent of the LLM — it walks the dependency graph and dispatches steps in parallel up to the concurrency cap.
- Each parallel step gets its own `step_usage` ContextVar so token usage isn't polluted across coroutines.
- Workflow templates (`workflows/*.yaml`) provide reusable Plan skeletons (data_report, competitor_analysis, meeting_minutes, activity_plan, product_prd).

### Shared Infrastructure (`backend/agent/v2/`)

- `llm.py` — Factory creating ChatOpenAI / ChatDashScope / DeepSeekV4ChatOpenAI instances based on `request_context.get_request_model()`. Includes a custom DeepSeek V4 adapter for `reasoning_content` streaming and orphan tool-call repair.
- `infra/executor_impl.py` — E2B remote sandbox + local subprocess executor with the executor → validator → fixer self-check loop (max 3 fix attempts).
- `infra/validator.py` — Classifies execution failures and triggers fixer prompts.

### Tools (`backend/tools/`)

`ALL_TOOLS` (exported via `__init__.py`) bundles **12 categories**:

- `web_search.py` — DuckDuckGo / Google / Bing RSS fallback + Jina AI crawl (3 tools)
- `calculator.py` — Safe math eval + descriptive stats (2 tools)
- `visualization.py` — Plotly interactive chart generation (1 tool, dark template)
- `sandbox.py` — E2B remote sandbox / local subprocess fallback (1 tool)
- `duckdb_tools.py` — `list_tables` / `query_duckdb` with `request_context.get_table_scope()` enforcement (system tables blocked)
- `heavy_tools.py` — `run_in_sandbox` with auto-validation
- `export_conversation.py` — `generate_docx` (Markdown → DOCX/PDF) and `EXPORT_TOOLS` for legacy export
- `task_manager.py` — Persistent GTD task CRUD (per-thread)
- `knowledge_base.py` — ChromaDB semantic search
- `user_memory.py` — preference / fact / experience / context memory store
- `cron_manager.py` — APScheduler-based cron task management
- `user_interaction.py` — `ask_user` / `request_confirmation`

### Backend Services

- `db_utils.py` — DuckDB data management: CSV/Excel import, external DB attach (MySQL/PG), data profiling, table listing
- `search_service.py` — Pure stdlib search engine (urllib + regex + html parser), no extra dependencies; this file is also shipped into the sandbox so generated code can call the same engine
- `prompt_loader.py` — Assembles the Solo system prompt from base + persona + user_extra + dynamic hints
- `skill_loader.py` — Loads skill metadata from `.trae/skills/` for the SSE `tool_start` payload
- `state_store.py` — SQLite persistence for cron tasks and alerts
- `conversation_store.py` — SQLite per-user conversation history (auto-trim to 500)
- `memory.py` — ChromaDB structured vector memory (preference / fact / experience / context); used by `/api/chat` for context retrieval and post-reply storage
- `checkpoint_store.py` — LangGraph checkpoint persistence (SQLite-backed)
- `report_generator.py` — Multi-format report generation (Markdown, HTML, PDF, DOCX)
- `request_context.py` — Per-request ContextVar (model selection, usage tracking, attached charts, export content, table scope)
- `local_exec_runner.py` — Local subprocess executor with dangerous-import scanning

### Frontend (`frontend/src/`)

Vue 3 Options API + Vite build + single reactive store (no Pinia, no TypeScript, no vue-router):

```
store.js              # ~120-line single reactive({}) with ALL app state, including agentMode
components/           # ChatView (router), SoloChatView, TeamChatView, ChatMessage, Sidebar, ContextPanel, etc.
composables/          # useChat.js (SSE handling), useHistory.js, useSettings.js, usePreferences.js
utils/                # charts.js (Plotly helpers), sse.js, crypto.js
```

Views switch via `v-if` on `store.agentMode` (no router). SSE streaming flows through `useChat.js`, which dispatches event handlers per event type. Switching mode snapshots the current session into `soloSession`/`teamSession` so each mode keeps its own message list and artifacts.

### Data Flow

```
Frontend (Vue)  →  POST/SSE  →  FastAPI (backend/api.py)
                                    │
                                    ├─ /api/chat       → build_single_agent_graph() (Solo)
                                    ├─ /api/v2/chat    → TeamMTCRuntime.run() (Team MTC)
                                    │                    ↓ (env flag)
                                    │                    TeamOrchestrationRuntime (legacy)
                                    ├─ /api/v2/workflows / /api/v2/plan/{tid} / /api/v2/tasks
                                    ├─ /api/upload     → DuckDB import or artifacts/ landing
                                    ├─ /api/tables, /api/table_data/* → DuckDB queries
                                    ├─ /api/conversations* → SQLite history
                                    ├─ /api/schedule, /api/alerts → APScheduler + SQLite
                                    └─ /api/settings   → env var injection (⚠️ optional Access Code auth)
```

### Storage

- `data/data.duckdb` — DuckDB for uploaded data
- `data/app_state.db` — SQLite for tasks, alerts, conversations, MTC plan/step/artifact persistence
- `data/checkpoints.db` — LangGraph checkpoint store
- `chroma_db/` — ChromaDB vector store
- `artifacts/` — Generated charts (HTML/PNG), reports, exports, parsed file uploads

## Key Constraints & Patterns

- **Model API**: Defaults to DashScope (Qwen3.6-Plus); supports OpenAI and DeepSeek via `request_context.get_request_model()`. Available models gated by which API keys are configured.
- **Auth**: Optional `SPECTRA_ACCESS_CODE` env var; when set, all `/api/*` calls require `Authorization: Bearer <code>`. CORS allows `*`. API keys can be set at runtime via `/api/settings`.
- **Single user**: Designed as single-user local/self-hosted. `conversation_store` has `user_id` field but defaults to `"default"`.
- **Streaming**: Chat endpoints use SSE (`sse-starlette`). The MTC runtime yields internal events that `api.py` translates via `SSETranslator` into SSE.
- **Table scope**: `request_context.set_table_scope()` restricts which DuckDB tables the agent can see for that request; `list_tables` / `query_duckdb` enforce this.
- **Error handling**: Most endpoints return `{"error": str(e)}` with HTTP 200 rather than using `HTTPException`. Frontend checks `response.error`.
- **Feature flag**: `SPECTRA_TEAM_MTC_ENABLED=0` falls back to legacy Team Supervisor for `/api/v2/chat`.
- **Deprecated**: `@app.on_event("startup")` / `"shutdown"` — should migrate to FastAPI lifespan handler.
