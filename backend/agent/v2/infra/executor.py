"""Executor 的 v2 入口。"""

from __future__ import annotations

from backend.agent.v2.infra.executor_impl import executor_node as _executor_node

__all__ = ["run_executor"]


def run_executor(legacy_state: dict) -> dict:
    """执行成员 Agent 生成的 Python 代码（E2B / 本地双引擎）。"""
    return _executor_node(legacy_state)
