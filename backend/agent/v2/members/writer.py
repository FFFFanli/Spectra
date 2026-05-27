"""
Writer 成员 Agent。

合并 legacy reporter + planner 的能力，永远走 LLM 实时生成 reportlab/python-docx 代码。
不再有"模板路径"。validator 强校验：必须有 PDF/DOCX 产物，否则进 fixer 修复。
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from backend.agent.v2.infra.skills import resolve_skill_for_member
from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.writer import build_writer_prompt


class WriterMember(BaseMember):
    """正式文档生成器（PDF / DOCX）。"""

    name = "writer"
    requires_code_execution = True

    def build_prompt(self, ctx: MemberContext) -> str:
        # 上游产物：从 ctx.upstream_artifacts 和 ctx.extra 里读
        upstream_artifacts = ctx.upstream_artifacts or ctx.extra.get("upstream_artifacts", "（无上游产物）")
        if isinstance(upstream_artifacts, list):
            upstream_artifacts = "\n".join(
                f"- {a.get('name', a.get('type', ''))}: {a.get('url', a.get('summary', ''))}"
                for a in upstream_artifacts
            ) or "（无上游产物）"
        chart_png_hint = ctx.extra.get("chart_png_hint", "")

        skill_brief = "（无匹配 Skill）"
        if ctx.skill_name:
            skill_brief = (
                f"已匹配 Skill `{ctx.skill_name}` (capability={ctx.skill_capability}): "
                f"{ctx.extra.get('skill_description', '') or ''}"
            )

        output_format = ctx.output_format or ctx.extra.get("output_format", "pdf")

        return build_writer_prompt(
            schema=ctx.schema,
            upstream_artifacts=upstream_artifacts,
            skill_brief=skill_brief,
            chart_png_hint=chart_png_hint,
            output_format=output_format,
        )

    def default_reply(self) -> str:
        return "writer 已生成正式报告代码并执行完毕。"

    def _validator_sender_alias(self) -> str:
        # legacy validator 对 sender='reporter' 做强校验：必须有 pdf/docx 报告，
        # 否则触发 fixer。这正是我们想要的行为。
        return "reporter"

    def attach_skill(self, ctx: MemberContext) -> None:
        """在执行前查找并注入 skill 上下文（W3 新增）。"""
        skill, auto_created = resolve_skill_for_member(ctx.task_goal or ctx.instruction, "writer")
        if skill is None:
            return
        ctx.skill_name = skill.name
        ctx.skill_path = ""  # SkillDef 无 path 字段
        ctx.skill_capability = skill.capability
        ctx.extra["skill_description"] = skill.description
        ctx.extra["skill_auto_created"] = auto_created

    async def execute(self, ctx, on_event=None):
        # 在跑 LLM 之前先解析 skill
        self.attach_skill(ctx)
        return await super().execute(ctx, on_event=on_event)
