"""
Skill 匹配：v2 成员 Agent 在执行前调用 resolve_skill_for_member 取得当前任务对应的 skill。

设计要点：
- 同一个 capability 支持新旧 agent 名同时存在：
  - 旧 SKILL.md 里的 agent: 'reporter' / 'planner' / 'form_filler' 全部归属到 v2 的 'writer'
  - 旧 SKILL.md 里的 agent: 'researcher' 归属到 v2 的 'researcher'（名称不变）
- 这样无需立即改动 .trae/skills/*/SKILL.md
"""

from __future__ import annotations

from typing import Optional

from backend.skill_loader import SkillDef, get_skills


# v2 成员 → 兼容的 legacy agent 名集合
_AGENT_ALIAS_MAP: dict[str, list[str]] = {
    "writer": ["writer", "reporter", "planner", "form_filler"],
    "researcher": ["researcher"],
    "coder": ["coder", "analyzer", "visualizer", "predictor", "cleaner"],
}


def resolve_skill_for_member(
    task_goal: str,
    member_id: str,
) -> tuple[Optional[SkillDef], bool]:
    """根据成员名查找最匹配的 skill。

    Returns:
        (skill, auto_created)。auto_created 目前始终为 False（自动创建逻辑待实现）。
    """
    if not task_goal:
        return None, False

    aliases = _AGENT_ALIAS_MAP.get(member_id, [member_id])
    skills = get_skills()

    # 找第一个 agent 字段匹配的 skill（简单匹配策略）
    for skill in skills:
        if skill.agent in aliases:
            return skill, False

    return None, False


__all__ = ["resolve_skill_for_member", "SkillDef"]
