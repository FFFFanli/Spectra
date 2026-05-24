"""
从 .trae/skills/ 目录加载 SKILL.md 定义，构建 tool→skill 映射。
用于 system prompt 注入和 SSE 事件中的 skill 识别。
"""

from __future__ import annotations

import re
import yaml
from pathlib import Path
from dataclasses import dataclass, field


SKILLS_DIR = Path(__file__).resolve().parent.parent / ".trae" / "skills"


@dataclass
class SkillDef:
    name: str
    description: str
    capability: str
    triggers: str
    tools: list[str] = field(default_factory=list)
    agent: str = ""
    body: str = ""


def _parse_skill_md(filepath: Path) -> SkillDef | None:
    """解析单个 SKILL.md 文件，返回 SkillDef 或 None。"""
    text = filepath.read_text(encoding="utf-8")
    # 匹配 YAML frontmatter
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not m:
        return None

    try:
        meta = yaml.safe_load(m.group(1))
    except Exception:
        return None

    if not isinstance(meta, dict) or not meta.get("name"):
        return None

    return SkillDef(
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        capability=meta.get("capability", ""),
        triggers=meta.get("triggers", ""),
        tools=meta.get("tools") or [],
        agent=meta.get("agent", ""),
        body=m.group(2).strip(),
    )


def load_skills() -> list[SkillDef]:
    """加载所有 SKILL.md 定义。"""
    skills: list[SkillDef] = []
    if not SKILLS_DIR.exists():
        return skills
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        md_path = skill_dir / "SKILL.md"
        if not md_path.exists():
            continue
        skill = _parse_skill_md(md_path)
        if skill:
            skills.append(skill)
    return skills


def build_tool_skill_map(skills: list[SkillDef]) -> dict[str, SkillDef]:
    """构建 tool_name → SkillDef 的映射表。"""
    mapping: dict[str, SkillDef] = {}
    for skill in skills:
        for tool in skill.tools:
            tool = tool.strip()
            if tool and tool not in mapping:
                mapping[tool] = skill
    return mapping


# 模块级缓存，首次 import 时加载
_SKILLS: list[SkillDef] | None = None
_TOOL_SKILL_MAP: dict[str, SkillDef] | None = None


def get_skills() -> list[SkillDef]:
    global _SKILLS
    if _SKILLS is None:
        _SKILLS = load_skills()
    return _SKILLS


def get_tool_skill_map() -> dict[str, SkillDef]:
    global _TOOL_SKILL_MAP
    if _TOOL_SKILL_MAP is None:
        _TOOL_SKILL_MAP = build_tool_skill_map(get_skills())
    return _TOOL_SKILL_MAP


def find_skill_for_tool(tool_name: str) -> SkillDef | None:
    return get_tool_skill_map().get(tool_name)


def build_skills_system_prompt() -> str:
    """生成注入到 system prompt 的技能说明片段。"""
    skills = get_skills()
    if not skills:
        return ""

    lines = [
        "",
        "<available_skills>",
        "你可以使用以下高层技能来完成任务。每个技能对应一组底层工具：",
        "",
    ]
    for s in skills:
        tool_list = "、".join(s.tools) if s.tools else "（无特定工具）"
        lines.append(f"**{s.name}** — {s.description}")
        lines.append(f"  关联工具：{tool_list}")
        lines.append("")
    lines.append("</available_skills>")
    return "\n".join(lines)
