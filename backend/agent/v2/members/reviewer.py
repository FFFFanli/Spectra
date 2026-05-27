"""
Reviewer 成员 Agent。

负责对其他 Member_Agent 的产物执行质量复核：
  1. 产物文件存在
  2. 关键数字与上下文一致
  3. 引用来源可访问

产出复核报告文本。

满足：R4.3
"""

from __future__ import annotations

from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.reviewer import build_reviewer_prompt


class ReviewerMember(BaseMember):
    """质量复核员：检查产物完整性与可信度。"""

    name = "reviewer"
    requires_code_execution = False  # Reviewer 只出复核报告文本

    def build_prompt(self, ctx: MemberContext) -> str:
        upstream_artifacts = ctx.extra.get("upstream_artifacts", "")
        return build_reviewer_prompt(
            schema=ctx.schema,
            upstream_artifacts=upstream_artifacts,
            task_goal=ctx.task_goal,
        )

    def default_reply(self) -> str:
        return "reviewer 已完成质量复核。"
