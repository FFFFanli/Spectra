"""
Skill Registry 包装 —— Phase 1 后 skill_registry 已删除，此模块保留为兼容桩。
resolve_skill_for_member 始终返回 (None, False)。
"""

from __future__ import annotations

from typing import Optional


# 保留 SkillDefinition 类型占位，避免 member 代码 import 报错
class SkillDefinition:
    name: str = ""
    description: str = ""
    body: str = ""
    path: str = ""
    owning_agent: str = ""
    capability: str = ""
    trigger_keywords: list[str] = []
    auto_created: bool = False


def resolve_skill_for_member(
    task_goal: str,
    member_id: str,
) -> tuple[Optional[SkillDefinition], bool]:
    """Phase 1 后 skill 系统已移除，始终返回无匹配。"""
    return None, False


__all__ = ["resolve_skill_for_member", "SkillDefinition"]
