"""
Responder 成员 Agent。

直接回答用户，不需要代码执行。用于闲聊、概念解释等场景。
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.v2.llm import _create_llm
from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.responder import build_responder_prompt
from backend.agent.v2.state import AgentResult


class ResponderMember(BaseMember):
    """团队发言人：直接文字回复，无需代码执行。"""

    name = "responder"
    requires_code_execution = False

    def build_prompt(self, ctx: MemberContext) -> str:
        return build_responder_prompt(instruction=ctx.instruction)

    def default_reply(self) -> str:
        return "responder 已直接回答用户。"
