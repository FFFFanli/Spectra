"""
Coder 成员 Agent。

合并 legacy cleaner + analyzer + visualizer + predictor 能力，
统一为"写 Python 处理 DuckDB 数据"。
"""

from __future__ import annotations

from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.coder import build_coder_prompt


class CoderMember(BaseMember):
    """数据工程师：写 Python 处理 DuckDB，产出清洗文件/图表/分析结论。"""

    name = "coder"
    requires_code_execution = True

    def build_prompt(self, ctx: MemberContext) -> str:
        skill_brief = "（无匹配 Skill）"
        if ctx.skill_name:
            skill_brief = (
                f"已匹配 Skill `{ctx.skill_name}` (capability={ctx.skill_capability}): "
                f"{ctx.extra.get('skill_description', '') or ''}"
            )
        return build_coder_prompt(
            instruction=ctx.instruction,
            schema=ctx.schema,
            skill_brief=skill_brief,
        )

    def default_reply(self) -> str:
        return "coder 已完成数据处理与代码执行。"

    def _validator_sender_alias(self) -> str:
        # legacy validator 对 sender='analyzer' 做最宽松校验（stdout 非空 + 无运行时错误）
        return "analyzer"
