"""Fixer 的 v2 入口。"""

from __future__ import annotations

from backend.agent.v2.infra.executor_impl import fixer_node as _fixer_node

__all__ = ["run_fixer"]


def run_fixer(legacy_state: dict) -> dict:
    """根据 validator 的诊断让 LLM 生成修复后的代码。"""
    return _fixer_node(legacy_state)
