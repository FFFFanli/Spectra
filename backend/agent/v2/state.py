"""
TeamState —— v2 Supervisor 编排的状态定义。

State 常量命名对齐 LobeHub GroupOrchestrationSupervisor 的决策阶跃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import BaseMessage

# AgentResult 定义已迁移至 members.base，此处保留重导出以兼容 legacy_runtime
from backend.agent.v2.members.base import AgentResult  # noqa: F401

# ── 已知 Agent 集合 ──────────────────────────────────────────────
KNOWN_AGENTS = ("coder", "writer", "researcher", "responder")

AGENT_MODEL_DEFAULTS: dict[str, str] = {
    "coder":      "qwen-plus",
    "writer":     "qwen-max",
    "researcher": "qwen-plus",
    "responder":  "qwen-plus",
    "supervisor": "qwen-plus",
}

# ── 状态常量 ─────────────────────────────────────────────────────
INIT = "init"
CALL_SUPERVISOR = "call_supervisor"
SUPERVISOR_PLAN = "supervisor_plan"
CALL_AGENT = "call_agent"
PARALLEL_CALL_AGENTS = "parallel_call_agents"
SPAWN_BACKGROUND_TASK = "spawn_background_task"
SPAWN_BACKGROUND_TASKS = "spawn_background_tasks"
AGENT_DONE = "agent_done"
AGENTS_DONE = "agents_done"
TASK_DONE = "task_done"
ALL_TASKS_DONE = "all_tasks_done"
REPLY_AND_FINISH = "reply_and_finish"
FINISH = "finish"


@dataclass
class TeamState:
    """Supervisor 决策循环中的完整状态。"""

    messages: list[BaseMessage] = field(default_factory=list)
    round_count: int = 0
    max_rounds: int = 8
    current_instruction: str = ""
    current_phase: str = INIT

    # 并行 / 异步执行结果
    parallel_outputs: dict[str, AgentResult] = field(default_factory=dict)
    pending_tasks: list[str] = field(default_factory=list)          # task_id 列表
    background_results: dict[str, AgentResult] = field(default_factory=dict)

    # 全局产物收集
    artifacts: list[dict] = field(default_factory=list)
    chart_path: Optional[str] = None
    chart_png_path: Optional[str] = None
    report_path: Optional[str] = None
    pdf_report_path: Optional[str] = None

    # 元信息
    thread_id: str = ""
    user_message: str = ""
    schema: str = ""

    # 版本标记（checkpoint 兼容性）
    version: int = 2


def make_initial_state(
    user_message: str = "",
    schema: str = "",
    thread_id: str = "",
) -> TeamState:
    return TeamState(
        messages=[],
        round_count=0,
        max_rounds=8,
        current_phase=INIT,
        user_message=user_message,
        schema=schema,
        thread_id=thread_id,
        version=2,
    )
