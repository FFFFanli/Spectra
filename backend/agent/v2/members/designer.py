"""
Designer 成员 Agent。

负责输出 PPT 大纲、章节版式与配色建议（产物为 JSON 描述结构，
由 Writer_Agent 落地为 pptx 文件）。

满足：R4.2
"""

from __future__ import annotations

from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.designer import build_designer_prompt


class DesignerMember(BaseMember):
    """PPT 大纲与版式设计师。"""

    name = "designer"
    requires_code_execution = False  # Designer 只出 JSON 结构，不执行代码

    def build_prompt(self, ctx: MemberContext) -> str:
        upstream_artifacts = ctx.extra.get("upstream_artifacts", "")
        return build_designer_prompt(
            schema=ctx.schema,
            upstream_artifacts=upstream_artifacts,
        )

    def default_reply(self) -> str:
        return "designer 已生成 PPT 大纲与版式建议。"
