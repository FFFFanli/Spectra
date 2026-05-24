# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Spectra is a multi-agent data analysis platform built with **FastAPI + LangGraph + DuckDB + Vue 3**. It supports three agent collaboration modes, web search, automated workflows, and scheduled monitoring.

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

### Agent Modes (3 modes, user selects or auto-detect)

| Mode | File | Description |
|------|------|-------------|
| **Solo** | `backend/agent/single_agent.py` | Single LLM ↔ Tool loop via LangGraph `StateGraph`. LLM decides tool calls autonomously. |
| **Team Supervisor v2** | `backend/agent/v2/runtime.py` | Supervisor + Coder/Writer/Researcher/Responder multi-member orchestration with executor→validator→fixer self-check loop. This is the primary mode — `/api/chat`. |
| **Graph Agent** | `backend/agent/graph_agent.py` | Dynamic DAG pipeline where each node is an independent subgraph. Supports 5 predefined workflows. |

### Agent v2 Internals (`backend/agent/v2/`)

The v2 runtime is the most important code path:

```
runtime.py          # TeamOrchestrationRuntime — main event loop, yields internal events consumed by api.py SSE
planner.py          # SupervisorPlanner — pure state machine (no LLM calls), maps ExecutorResult → Instruction
state.py            # TeamState, state constants (INIT, CALL_SUPERVISOR, CALL_AGENT, FINISH, etc.)
llm.py              # LLM factory: creates ChatOpenAI / ChatDashScope instances based on selected model
tools.py            # Supervisor's tool definitions (assign, broadcast, respond, finish, etc.)
members/            # Agent team members
  base.py           # BaseMember abstract class with execute(ctx) interface
  coder.py          # Coder — code generation + execution via sandbox
  researcher.py     # Researcher — web search + crawling
  writer.py         # Writer — report/markdown generation
  responder.py      # Responder — final response composition
infra/task_runner.py # Background task spawning for async execution
prompts/            # System prompts for supervisor and each member
```

Key design principle of v2: `SupervisorPlanner.decide()` is a **pure function** — given state + result, returns (new_state, instruction). The LLM decision is made by `Runtime` which receives the `call_supervisor` instruction, calls the LLM with supervisor tools, and feeds the tool_call result back as a `supervisor_plan` ExecutorResult.

### Tools (`backend/tools/`)

7 LangChain tools in `ALL_TOOLS` (exported via `__init__.py`):
- `web_search.py` — DuckDuckGo search + Jina AI crawl (3 tools)
- `calculator.py` — Safe math expression eval + descriptive stats (2 tools)
- `visualization.py` — ECharts interactive chart generation (1 tool)
- `sandbox.py` — E2B remote sandbox / local subprocess fallback (1 tool)
- `export_conversation.py` — DOCX export via `generate_docx` (replaces old `export_conversation` tool in single-agent list)

### Backend Services

- `db_utils.py` — DuckDB data management: CSV/Excel import, external DB attach (MySQL/PG), data profiling, table listing
- `search_service.py` — Pure stdlib search engine (urllib + regex + html parser), no extra dependencies
- `skill_registry.py` — Skill definitions loaded from `.trae/skills/` directory, with built-in fallbacks and keyword-triggered retrieval
- `state_store.py` — SQLite persistence for cron tasks and alerts
- `conversation_store.py` — SQLite persistence for conversation history (per-user, auto-trim to 500)
- `memory.py` — ChromaDB vector-based conversation memory (note: defined but not wired into chat flow)
- `checkpoint_store.py` — LangGraph checkpoint persistence (SQLite-backed)
- `report_generator.py` — Multi-format report generation (Markdown, HTML, PDF, DOCX)
- `request_context.py` — Per-request context (model selection, usage tracking, chart/export attachments)

### Frontend (`frontend/src/`)

Vue 3 Options API + single reactive store (no Pinia, no TypeScript, no vue-router):

```
store.js              # ~120-line single reactive({}) with ALL app state
components/           # Vue components: ChatView, ChatMessage, Sidebar, ContextPanel, etc.
composables/          # useChat.js, useHistory.js, useSettings.js, usePreferences.js
utils/                # charts.js (ECharts helpers)
```

Views are switched via `v-if` on `store.currentView` (no router). SSE streaming goes through `useChat.js`.

### Data Flow

```
Frontend (Vue)  →  POST/SSE  →  FastAPI (backend/api.py)
                                    │
                                    ├─ /api/chat → TeamOrchestrationRuntime (v2)
                                    ├─ /api/agent/chat → single_agent.build_single_agent_graph()
                                    ├─ /api/graph/stream → build_graph_agent()
                                    ├─ /api/upload → DuckDB import
                                    ├─ /api/tables, /api/table_data/* → DuckDB queries
                                    └─ /api/settings → env var injection (⚠️ no auth)
```

### Storage

- `data/spectra.duckdb` — DuckDB for uploaded data
- `data/app_state.db` — SQLite for tasks, alerts, conversations, checkpoint
- `chroma_db/` — ChromaDB vector store
- `artifacts/` — Generated charts (HTML/PNG), reports, exports

## Key Constraints & Patterns

- **Model API**: Uses DashScope (Qwen) by default, supports OpenAI and DeepSeek via `request_context.get_request_model()`
- **No auth**: All API endpoints are open. CORS allows `*`. API keys are stored in env vars and can be set at runtime via `/api/settings`.
- **Single user**: Designed as a single-user local/self-hosted deployment. `conversation_store` has `user_id` field but always uses `"default"`.
- **Streaming**: Chat endpoints use SSE (`sse-starlette`) with `StreamingResponse`-like patterns. The v2 runtime yields internal events that `api.py` translates to SSE.
- **Error handling**: Most endpoints return `{"error": str(e)}` with HTTP 200 rather than using `HTTPException`. Frontend checks `response.error`.
- **Deprecated**: `@app.on_event("startup")` / `"shutdown"` — should migrate to lifespan handler in FastAPI.
