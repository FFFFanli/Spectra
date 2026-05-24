"""
从 .trae/prompts/ 目录加载 prompt 文件。
prompt 内容存于 .md 文件中，运维可直接编辑，无需改代码。
"""

from __future__ import annotations
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / ".trae" / "prompts"

# 模块级缓存
_CACHE: dict[str, str] = {}


def _load_prompt(name: str) -> str:
    """加载单个 prompt 文件，带缓存。"""
    if name not in _CACHE:
        filepath = PROMPTS_DIR / f"{name}.md"
        if filepath.exists():
            _CACHE[name] = filepath.read_text(encoding="utf-8").strip()
        else:
            _CACHE[name] = ""
    return _CACHE[name]


def get_agent_base_prompt() -> str:
    """Agent 行为规范 prompt（原 SINGLE_AGENT_BASE_PROMPT）。"""
    return _load_prompt("agent-base")


def get_sandbox_prompt() -> str:
    """沙盒环境 + 预装库 + python_guidelines + export_policy 等。"""
    return _load_prompt("sandbox")


def get_chart_prompt() -> str:
    """ECharts 图表输出规范。"""
    return _load_prompt("chart")


def get_skills_prompt() -> str:
    """Skill 定义 prompt 片段（由 skill_loader 提供）。"""
    from backend.skill_loader import build_skills_system_prompt
    return build_skills_system_prompt()


def build_system_prompt(
    persona_prompt: str = "",
    user_prompt: str = "",
    export_hint: str = "",
    attached_charts_brief: str = "",
    available_data_brief: str = "",
) -> str:
    """组装完整 system prompt。

    顺序：sandbox → attached_charts → available_data → skills → user_prompt → agent_base → chart → persona → export_hint
    """
    parts: list[str] = [
        get_sandbox_prompt(),
        attached_charts_brief,
        available_data_brief,
        get_skills_prompt(),
        user_prompt,
        get_agent_base_prompt(),
        get_chart_prompt(),
    ]
    if persona_prompt:
        parts.append(f"[角色设定]\n{persona_prompt}")
    if export_hint:
        parts.append(export_hint)
    return "\n\n".join(p for p in parts if p)


def reload_prompts() -> None:
    """清除缓存，强制下次访问时重新读取文件（热更新用）。"""
    _CACHE.clear()
