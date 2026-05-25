"""
Team Supervisor v2 —— 多 Agent 编排实现，对齐 LobeHub 群组架构。

架构：
- SupervisorPlanner: 纯状态机，不调 LLM
- TeamOrchestrationRuntime: 循环调度
- 6 种调度指令: assign / broadcast / execute_task / execute_tasks / respond / finish
- 4 个成员 Agent: coder / writer / researcher / responder
"""

from backend.agent.v2.state import TeamState, make_initial_state
from backend.agent.v2.planner import SupervisorPlanner
from backend.agent.v2.runtime import TeamOrchestrationRuntime

__all__ = [
    "TeamState",
    "make_initial_state",
    "SupervisorPlanner",
    "TeamOrchestrationRuntime",
]
