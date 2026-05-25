"""
BaseMember —— 成员 Agent 公共流程。

每个成员的 execute() 步骤：
  1. 让 LLM 根据 instruction 生成 (reply, code)
  2. 调 executor 执行 code
  3. 调 validator 校验产物
  4. 失败则调 fixer 修复，重试最多 max_retries 次
  5. 把产物 / reply / artifacts 包成 AgentResult 返回

子类只需要：
  - name: str（agent_id）
  - build_prompt(state, instruction) -> str
  - 默认产物 reply 兜底文案
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.agent.v2.infra.executor import run_executor
from backend.agent.v2.infra.fixer import run_fixer
from backend.agent.v2.infra.validator import run_validator
from backend.agent.v2.llm import _create_llm
from backend.agent.v2.state import AgentResult


MAX_FIX_RETRIES = 3


@dataclass
class MemberContext:
    """成员 Agent 执行时需要的最小上下文。"""

    instruction: str
    task_goal: str
    thread_id: str
    schema: str = ""
    skill_name: Optional[str] = None
    skill_path: Optional[str] = None
    skill_capability: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── 公共工具 ────────────────────────────────────────────────────

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def _extract_reply_and_code(content: str) -> tuple[str, str]:
    """从 LLM 响应中提取自然语言话术与代码。

    没有代码块时整段视为 code 兜底，避免 LLM 漏掉 ```python``` 包裹时整段被丢弃。
    """
    if not content:
        return "", ""
    match = _CODE_BLOCK_RE.search(content)
    if match:
        code = match.group(1).strip()
        reply = content[: match.start()].strip()
        return reply, code
    return content.strip(), ""


def _emit(stream: Optional[Callable[[dict], None]], event: dict) -> None:
    """安全的事件回调。"""
    if stream is None:
        return
    try:
        stream(event)
    except Exception as exc:  # pragma: no cover  防御性
        print(f"[v2.member] stream callback error: {exc}")


# ── BaseMember ─────────────────────────────────────────────────

class BaseMember:
    """所有成员 Agent 的基类。"""

    name: str = "base"           # 子类必须覆盖：agent_id
    requires_code_execution: bool = True  # 是否走 executor/validator/fixer 回路

    # ── 子类覆盖点 ─────────────────────────────────────────────
    def build_prompt(self, ctx: MemberContext) -> str:
        """返回 system prompt。子类必须覆盖。"""
        raise NotImplementedError

    def default_reply(self) -> str:
        """LLM 没给 reply 时的兜底文案。"""
        return f"{self.name} 已完成任务"

    # ── 主执行入口 ─────────────────────────────────────────────
    async def execute(
        self,
        ctx: MemberContext,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> AgentResult:
        """同步派单流程的核心：LLM → executor → validator → fixer。"""
        # 1. 让 LLM 生成代码
        system_prompt = self.build_prompt(ctx)
        reply, code = await asyncio.to_thread(
            self._invoke_llm_for_code, system_prompt, ctx.instruction, ctx.task_goal
        )
        if not reply:
            reply = self.default_reply()

        _emit(on_event, {
            "event": "agent_message",
            "agent_id": self.name,
            "reply": reply,
            "code": code,
        })

        # 不需要执行代码的成员（比如 responder）直接返回
        if not self.requires_code_execution:
            return AgentResult(
                agent_id=self.name,
                status="ok",
                reply=reply,
                code=None,
                artifacts=[],
                error=None,
            )

        if not code:
            return AgentResult(
                agent_id=self.name,
                status="failed",
                reply=reply,
                code=None,
                artifacts=[],
                error="LLM 未生成可执行代码",
            )

        # 2-4. executor → validator → fixer 回路
        legacy_state = self._initial_legacy_state(ctx, code)
        retry_count = 0

        while True:
            legacy_state["retry_count"] = retry_count
            legacy_state["max_retries"] = MAX_FIX_RETRIES

            # ── 2. executor 同步执行 ──
            exec_update = await asyncio.to_thread(run_executor, legacy_state)
            legacy_state.update(exec_update)
            _emit(on_event, {
                "event": "executor_done",
                "agent_id": self.name,
                "attempt_index": legacy_state.get("attempt_index", retry_count + 1),
                "execution_backend": legacy_state.get("execution_backend"),
                "artifacts": legacy_state.get("artifacts") or [],
                "chart_path": legacy_state.get("chart_path"),
                "chart_png_path": legacy_state.get("chart_png_path"),
                "cleaned_file_path": legacy_state.get("cleaned_file_path"),
                "report_path": legacy_state.get("report_path"),
                "pdf_report_path": legacy_state.get("pdf_report_path"),
                "execution_result": legacy_state.get("execution_result"),
            })

            # ── 3. validator 校验 ──
            legacy_state["sender"] = self._validator_sender_alias()
            validator_update = await asyncio.to_thread(run_validator, legacy_state)
            legacy_state.update(validator_update)

            if legacy_state.get("validation_passed"):
                _emit(on_event, {
                    "event": "validator_passed",
                    "agent_id": self.name,
                    "diagnostic": legacy_state.get("diagnostic"),
                })
                final_reply = legacy_state.get("reply") or reply
                return AgentResult(
                    agent_id=self.name,
                    status="ok",
                    reply=final_reply,
                    code=legacy_state.get("generated_code") or code,
                    artifacts=list(legacy_state.get("artifacts") or []),
                    error=None,
                )

            # ── 4. 校验失败：达到上限或继续 fixer ──
            diagnostic = legacy_state.get("diagnostic") or "执行失败但无诊断"
            _emit(on_event, {
                "event": "validator_failed",
                "agent_id": self.name,
                "diagnostic": diagnostic,
                "retry_count": retry_count,
            })

            if retry_count >= MAX_FIX_RETRIES:
                final_reply = legacy_state.get("reply") or (
                    f"{self.name} 修复 {MAX_FIX_RETRIES} 次后仍未通过校验：\n{diagnostic}"
                )
                return AgentResult(
                    agent_id=self.name,
                    status="failed",
                    reply=final_reply,
                    code=legacy_state.get("generated_code") or code,
                    artifacts=list(legacy_state.get("artifacts") or []),
                    error=diagnostic,
                )

            # 调 fixer 修复
            legacy_state.setdefault("repair_history", [])
            fixer_update = await asyncio.to_thread(run_fixer, legacy_state)
            legacy_state.update(fixer_update)
            retry_count = legacy_state.get("retry_count", retry_count + 1)

            _emit(on_event, {
                "event": "fixer_emitted",
                "agent_id": self.name,
                "fix_summary": legacy_state.get("fix_summary"),
                "retry_count": retry_count,
            })

    # ── 私有 helpers ───────────────────────────────────────────
    def _invoke_llm_for_code(
        self,
        system_prompt: str,
        instruction: str,
        task_goal: str,
    ) -> tuple[str, str]:
        """同步调用 LLM 生成 (reply, code)。线程安全，由 to_thread 调度。"""
        llm = _create_llm(temperature=0.1)
        user_msg = (
            f"【主任务目标】\n{task_goal or '（未提供）'}\n\n"
            f"【Supervisor 给你的子指令】\n{instruction}"
        )
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])
        return _extract_reply_and_code(getattr(response, "content", "") or "")

    def _initial_legacy_state(self, ctx: MemberContext, code: str) -> dict:
        """构造 executor_node 期望的 legacy state dict。"""
        return {
            "generated_code": code,
            "code_type": "python",
            "sender": self._validator_sender_alias(),
            "task_goal": ctx.task_goal,
            "configurable": {"thread_id": ctx.thread_id},
            "retry_count": 0,
            "max_retries": MAX_FIX_RETRIES,
            "selected_skill_name": ctx.skill_name,
            "selected_skill_path": ctx.skill_path,
            "selected_skill_capability": ctx.skill_capability,
            "messages": [HumanMessage(content=ctx.task_goal or ctx.instruction)],
        }

    def _validator_sender_alias(self) -> str:
        """v2 名称映射回 legacy validator 期望的 sender 字符串。

        legacy validator 校验逻辑按 sender 区分（cleaner 要 xlsx，reporter 要 pdf...）。
        v2 coder 覆盖了多种 legacy 角色，统一映射为 'analyzer'（最宽松校验：
        要求 stdout 非空 + 不能有运行时错误）。
        子类如果产物类型固定（writer 必须出 pdf），重写本方法返回对应 alias。
        """
        return "analyzer"
