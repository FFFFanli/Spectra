"""
Researcher 成员 Agent。

直接复用 legacy `_build_search_data_snippet`（agent 层预获取搜索结果 + 字面量注入）。
"""

from __future__ import annotations

from typing import Optional

# 直接复用 legacy 实现，避免代码漂移
from backend.agent.v2.members.researcher_search import (
    _build_search_data_snippet,
    _build_researcher_fallback_code,
    _researcher_code_needs_fallback,
)
from backend.agent.v2.infra.skills import resolve_skill_for_member
from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.researcher import build_researcher_prompt


class ResearcherMember(BaseMember):
    """联网搜索 + 结构化入库 + 报告摘要。"""

    name = "researcher"
    requires_code_execution = True

    def build_prompt(self, ctx: MemberContext) -> str:
        # 取出 attach_skill 时已经写进 ctx.extra 的搜索片段
        snippet = ctx.extra.get("search_data_snippet", "")
        skill_brief = "（无匹配 Skill）"
        if ctx.skill_name:
            skill_brief = (
                f"已匹配 Skill `{ctx.skill_name}` (capability={ctx.skill_capability}): "
                f"{ctx.extra.get('skill_description', '') or ''}"
            )
        return build_researcher_prompt(
            instruction=ctx.instruction,
            schema=ctx.schema,
            search_data_snippet=snippet,
            skill_brief=skill_brief,
        )

    def default_reply(self) -> str:
        return "researcher 已根据预获取的搜索结果生成数据处理代码。"

    def _validator_sender_alias(self) -> str:
        # legacy validator 对 sender='researcher' 做相应校验（必须有 stdout，搜到内容）
        return "researcher"

    def attach_skill(self, ctx: MemberContext) -> None:
        """在执行前预取搜索结果 + 解析 skill 一次性塞进 ctx.extra。"""
        # 1. 解析 skill（不强制）
        skill, auto_created = resolve_skill_for_member(
            ctx.task_goal or ctx.instruction, "researcher"
        )
        if skill is not None:
            ctx.skill_name = skill.name
            ctx.skill_path = ""  # SkillDef 无 path 字段
            ctx.skill_capability = skill.capability
            ctx.extra["skill_description"] = skill.description
            ctx.extra["skill_auto_created"] = auto_created

        # 2. 预获取搜索结果
        query = (ctx.instruction or ctx.task_goal or "").strip() or "AI 行业最新动态"
        snippet, sr_count, crawled_count = _build_search_data_snippet(query)
        ctx.extra["search_data_snippet"] = snippet
        ctx.extra["search_result_count"] = sr_count
        ctx.extra["crawled_result_count"] = crawled_count

    async def execute(self, ctx, on_event=None):
        self.attach_skill(ctx)

        # 在执行 LLM 之前，把搜索元信息作为事件下发（前端能立刻看到搜了多少条）
        if on_event:
            on_event({
                "event": "researcher_search_done",
                "agent_id": self.name,
                "search_result_count": ctx.extra.get("search_result_count", 0),
                "crawled_result_count": ctx.extra.get("crawled_result_count", 0),
            })

        result = await super().execute(ctx, on_event=on_event)

        # 后处理：检查 LLM 写出来的代码是否仍包含违禁 import
        # 如果需要 fallback，用 legacy 的安全模板替换
        # 注意：BaseMember 在 LLM 阶段把 code 喂进了 executor 之后才发现违禁，
        # 但当前 result.code 是修复后的最终代码。这里只做"如果完全没有 _SEARCH_RESULTS"的兜底。
        if result.get("status") == "failed":
            code = result.get("code") or ""
            if _researcher_code_needs_fallback(code):
                # 用 legacy 的安全 fallback 代码重跑一次
                fallback_code = _build_researcher_fallback_code(
                    ctx.extra.get("search_data_snippet", "")
                )
                if on_event:
                    on_event({
                        "event": "researcher_fallback_used",
                        "agent_id": self.name,
                        "reason": "llm_emitted_forbidden_imports",
                    })
                # 用 fallback code 直接走一次 executor（不走 fixer 循环，因为已经定型）
                from backend.agent.v2.infra.executor import run_executor
                from backend.agent.v2.infra.validator import run_validator
                import asyncio

                legacy_state = self._initial_legacy_state(ctx, fallback_code)
                exec_update = await asyncio.to_thread(run_executor, legacy_state)
                legacy_state.update(exec_update)
                legacy_state["sender"] = "researcher"
                val_update = await asyncio.to_thread(run_validator, legacy_state)
                legacy_state.update(val_update)
                if legacy_state.get("validation_passed"):
                    return {
                        "agent_id": self.name,
                        "status": "ok",
                        "reply": legacy_state.get("reply") or "已使用安全模板生成搜索报告。",
                        "code": fallback_code,
                        "artifacts": list(legacy_state.get("artifacts") or []),
                        "error": None,
                    }
        return result
