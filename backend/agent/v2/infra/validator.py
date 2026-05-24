"""Validator 的 v2 入口。"""

from __future__ import annotations

from backend.agent.v2.infra.executor_impl import validator_node as _validator_node

__all__ = ["run_validator"]


def run_validator(legacy_state: dict) -> dict:
    """校验 executor 产物。"""
    return _validator_node(legacy_state)
