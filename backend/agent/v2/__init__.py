"""
Team v2 —— 多 Agent 编排实现。

MTC 模式（默认）: TeamMTCRuntime — 统一执行体 + Plan 自动规划 + 并行调度
Legacy 模式（灰度回退）: TeamOrchestrationRuntime — Supervisor 调度多 Agent
"""

from backend.agent.v2.legacy_runtime import TeamOrchestrationRuntime
from backend.agent.v2.mtc.runtime import TeamMTCRuntime

__all__ = [
    "TeamOrchestrationRuntime",
    "TeamMTCRuntime",
]
