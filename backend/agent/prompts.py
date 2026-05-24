"""
Agent 共享提示词模块 —— 委托到 prompt_loader 从 .md 文件加载。
保留此文件是为了兼容旧 import 路径；新代码应直接使用 backend.prompt_loader。
"""

from backend.prompt_loader import (
    get_sandbox_prompt,
    get_chart_prompt,
    get_agent_base_prompt,
    build_system_prompt,
    reload_prompts,
)

# 兼容旧代码的模块级常量
SANDBOX_SYSTEM_PROMPT = get_sandbox_prompt()
CHART_PROMPT = get_chart_prompt()
AGENT_BASE_PROMPT = get_agent_base_prompt()
