"""
TeamOrchestrationRuntime —— v2 编排循环。

W4 实装:
  - INIT → call_supervisor → SUPERVISOR_PLAN（解析 LLM tool_call）
  - assign(coder|writer|researcher, ...) → 同步执行 → AGENT_DONE → 下一轮
  - broadcast(agent_ids, ...) → asyncio.gather 真正并行 → AGENTS_DONE → 下一轮
  - execute_task(agent_id, ...) → 后台线程池 + 立即返回 task_id
  - execute_tasks(...) → 批量后台并行
  - respond(text) → REPLY_AND_FINISH
  - finish(summary) → FINISH

本文件**不直接产出 SSE**，而是通过 yield 内部事件给上层 API 做翻译。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.v2.infra.task_runner import spawn_agent_task
from backend.agent.v2.llm import _create_llm
from backend.agent.v2.members.base import MemberContext
from backend.agent.v2.members.coder import CoderMember
from backend.agent.v2.members.researcher import ResearcherMember
from backend.agent.v2.members.responder import ResponderMember
from backend.agent.v2.members.writer import WriterMember
from backend.agent.v2.planner import (
    ExecutorResult,
    Instruction,
    SupervisorPlanner,
)
from backend.agent.v2.prompts.supervisor import build_supervisor_prompt
from backend.agent.v2.state import (
    AGENT_DONE,
    AGENTS_DONE,
    ALL_TASKS_DONE,
    CALL_AGENT,
    CALL_SUPERVISOR,
    FINISH,
    INIT,
    PARALLEL_CALL_AGENTS,
    REPLY_AND_FINISH,
    SPAWN_BACKGROUND_TASK,
    SPAWN_BACKGROUND_TASKS,
    SUPERVISOR_PLAN,
    TASK_DONE,
    TeamState,
    make_initial_state,
)
from backend.agent.v2.tools import SUPERVISOR_TOOLS


def _build_member_registry() -> dict[str, Any]:
    return {
        "coder": CoderMember(),
        "writer": WriterMember(),
        "researcher": ResearcherMember(),
        "responder": ResponderMember(),
    }


def _run_agent_in_thread(member, ctx: MemberContext, agent_id: str) -> dict:
    """在线程池中同步执行 async member.execute()。"""
    import asyncio as _asyncio
    loop = _asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(member.execute(ctx))
        if hasattr(result, '__dataclass_fields__'):
            return {
                "agent_id": result.agent_id,
                "status": result.status,
                "reply": result.reply,
                "code": result.code,
                "artifacts": result.artifacts,
                "error": result.error,
            }
        return result
    finally:
        loop.close()


class TeamOrchestrationRuntime:
    """v2 编排运行时。"""

    def __init__(self) -> None:
        self.planner = SupervisorPlanner()
        self.members = _build_member_registry()

    async def run(
        self,
        user_message: str,
        thread_id: str = "",
        schema: str = "",
        conversation_history: Optional[list] = None,
    ) -> AsyncIterator[dict]:
        """主入口：接收用户消息，yield 内部事件直到 FINISH。

        Yields 的事件 dict 格式:
          {"event": "supervisor_decision", "data": {...}}
          {"event": "agent_message", "data": {...}}
          {"event": "reply", "data": {"text": "..."}}
          {"event": "done", "data": {...}}
          {"event": "error", "data": {"message": "..."}}
        """
        if not thread_id:
            thread_id = uuid.uuid4().hex

        state = make_initial_state(
            user_message=user_message,
            schema=schema,
            thread_id=thread_id,
        )

        # 注入对话历史到 state.messages
        if conversation_history:
            for msg in conversation_history:
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role == "user":
                        state.messages.append(HumanMessage(content=content))
                    elif role == "assistant":
                        state.messages.append(SystemMessage(content=content))

        state.messages.append(HumanMessage(content=user_message))

        try:
            # 启动循环
            result = ExecutorResult(type=INIT)

            while True:
                instruction = await self._step(state, result)
                yield {"event": "supervisor_decision", "data": {
                    "type": instruction.type,
                    "payload": instruction.payload,
                }}

                # 执行指令
                result = await self._execute_instruction(state, instruction)

                # 检查终止条件
                if instruction.type == REPLY_AND_FINISH:
                    yield {"event": "reply", "data": {"text": instruction.payload.get("text", "")}}
                    break

                if instruction.type == FINISH:
                    summary = instruction.payload.get("summary", "") or "任务已完成。"
                    yield {"event": "reply", "data": {"text": summary}}
                    break

                if state.round_count >= state.max_rounds:
                    yield {"event": "reply", "data": {"text": f"已达到最大轮次 ({state.max_rounds})，任务终止。"}}
                    yield {"event": "done", "data": {
                        "reason": "max_rounds",
                        "rounds": state.round_count,
                        "artifacts": state.artifacts,
                    }}
                    break

            yield {"event": "done", "data": {
                "reason": instruction.type,
                "rounds": state.round_count,
                "artifacts": state.artifacts,
                "chart_path": state.chart_path,
                "chart_png_path": state.chart_png_path,
                "report_path": state.report_path,
                "pdf_report_path": state.pdf_report_path,
            }}

        except Exception as exc:
            yield {"event": "error", "data": {"message": str(exc)}}

    async def _step(self, state: TeamState, result: ExecutorResult) -> Instruction:
        """单步：planner.decide → 如果需要 supervisor 则调 LLM。"""
        new_state, instruction = self.planner.decide(state, result)
        state.current_phase = new_state.current_phase

        # 如果需要 supervisor 决策，调 LLM
        if instruction.type == CALL_SUPERVISOR:
            plan_result = await self._call_supervisor(state, instruction.payload)
            new_state, instruction = self.planner.decide(state, plan_result)
            state.current_phase = new_state.current_phase

        return instruction

    async def _execute_instruction(self, state: TeamState, instruction: Instruction) -> ExecutorResult:
        """根据指令类型执行实际动作。"""
        inst_type = instruction.type
        payload = instruction.payload

        if inst_type == CALL_AGENT:
            agent_id = payload.get("agent_id", "")
            inst_text = payload.get("instruction", "")
            member = self.members.get(agent_id)
            if member is None:
                return ExecutorResult(type=AGENT_DONE, payload={
                    "agent_id": agent_id,
                    "result": {"agent_id": agent_id, "status": "failed", "reply": f"未知 Agent: {agent_id}"},
                })

            ctx = MemberContext(
                instruction=inst_text,
                task_goal=state.user_message,
                thread_id=state.thread_id,
                schema=state.schema,
            )

            result = await self._run_agent(member, ctx, agent_id)
            return ExecutorResult(type=AGENT_DONE, payload={
                "agent_id": agent_id,
                "result": result,
            })

        elif inst_type == PARALLEL_CALL_AGENTS:
            agent_ids = payload.get("agent_ids", [])
            inst_text = payload.get("instruction", "")
            tasks = []
            for agent_id in agent_ids:
                member = self.members.get(agent_id)
                if member:
                    ctx = MemberContext(
                        instruction=inst_text,
                        task_goal=state.user_message,
                        thread_id=state.thread_id,
                        schema=state.schema,
                    )
                    tasks.append(self._run_agent(member, ctx, agent_id))
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            results = {}
            for agent_id, result in zip(agent_ids, results_list):
                if isinstance(result, Exception):
                    results[agent_id] = {"agent_id": agent_id, "status": "failed", "reply": str(result)}
                else:
                    results[agent_id] = result
            return ExecutorResult(type=AGENTS_DONE, payload={"results": results})

        elif inst_type == SPAWN_BACKGROUND_TASK:
            agent_id = payload.get("agent_id", "")
            title = payload.get("title", "")
            task = payload.get("task", "")
            timeout = payload.get("timeout", 600)
            member = self.members.get(agent_id)
            if member:
                ctx = MemberContext(
                    instruction=task,
                    task_goal=title or state.user_message,
                    thread_id=state.thread_id,
                    schema=state.schema,
                )
                task_id = spawn_agent_task(
                    agent_id, title,
                    _run_agent_in_thread, member, ctx, agent_id,
                    on_done=lambda r: state.background_results.update({r["task_id"]: r.get("result", {})}),
                )
                state.pending_tasks.append(task_id)
                return ExecutorResult(type=TASK_DONE, payload={
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "status": "pending",
                })
            return ExecutorResult(type=TASK_DONE, payload={
                "task_id": "",
                "agent_id": agent_id,
                "error": f"未知 Agent: {agent_id}",
            })

        elif inst_type == SPAWN_BACKGROUND_TASKS:
            tasks = payload.get("tasks", [])
            spawned = []
            for t in tasks:
                agent_id = t.get("agent_id", "")
                title = t.get("title", "")
                task = t.get("task", "")
                member = self.members.get(agent_id)
                if member:
                    ctx = MemberContext(
                        instruction=task,
                        task_goal=title or state.user_message,
                        thread_id=state.thread_id,
                        schema=state.schema,
                    )
                    task_id = spawn_agent_task(
                        agent_id, title,
                        _run_agent_in_thread, member, ctx, agent_id,
                        on_done=lambda r: state.background_results.update({r["task_id"]: r.get("result", {})}),
                    )
                    state.pending_tasks.append(task_id)
                    spawned.append({"task_id": task_id, "agent_id": agent_id, "status": "pending"})
            return ExecutorResult(type=TASK_DONE, payload={
                "spawned_tasks": spawned,
                "status": "pending",
            })

        elif inst_type == REPLY_AND_FINISH:
            return ExecutorResult(type=REPLY_AND_FINISH, payload=payload)

        elif inst_type == "wait_tasks":
            # 轮询等待后台任务完成（on_done 回调会更新 state.background_results）
            await asyncio.sleep(0.5)
            if not state.pending_tasks:
                return ExecutorResult(type=ALL_TASKS_DONE, payload={
                    "results": dict(state.background_results),
                })
            return ExecutorResult(type=TASK_DONE, payload={
                "remaining": len(state.pending_tasks),
            })

        elif inst_type == FINISH:
            return ExecutorResult(type=FINISH, payload=payload)

        else:
            return ExecutorResult(type=FINISH, payload={"reason": f"unknown_instruction: {inst_type}"})

    async def _run_agent(self, member, ctx: MemberContext, agent_id: str) -> dict:
        """执行单个成员 Agent，返回 AgentResult dict。"""
        try:
            result = await member.execute(ctx)
            # AgentResult 可能是 dataclass，转成 dict
            if hasattr(result, '__dataclass_fields__'):
                return {
                    "agent_id": result.agent_id,
                    "status": result.status,
                    "reply": result.reply,
                    "code": result.code,
                    "artifacts": result.artifacts,
                    "error": result.error,
                }
            return result
        except Exception as exc:
            return {
                "agent_id": agent_id,
                "status": "failed",
                "reply": "",
                "code": None,
                "artifacts": [],
                "error": str(exc),
            }

    async def _call_supervisor(self, state: TeamState, context: dict) -> ExecutorResult:
        """调用 LLM Supervisor，让其用 tool_call 做决策。"""
        llm = _create_llm(temperature=0.1).bind_tools(SUPERVISOR_TOOLS)
        schema = state.schema or "（未上传数据文件）"
        system_prompt = build_supervisor_prompt(schema=schema)

        # 构建对话上下文
        context_msg = (
            f"【当前轮次】第 {state.round_count + 1} 轮 / 最多 {state.max_rounds} 轮\n"
            f"【用户原始消息】{state.user_message}\n"
        )
        if context.get("agent_done"):
            context_msg += f"【上一轮 {context['agent_done']} 完成】见上方结果。请决定下一步。\n"
        if context.get("agents_done"):
            context_msg += f"【{', '.join(context['agents_done'])} 并行完成】见上方结果。请决定下一步。\n"
        if context.get("all_tasks_done"):
            context_msg += f"【所有后台任务完成】请汇总结果并 finish。\n"

        messages = [SystemMessage(content=system_prompt)]
        if state.messages:
            messages.extend(state.messages[-10:])  # 最近 10 条
        messages.append(HumanMessage(content=context_msg))

        response = await llm.ainvoke(messages)

        # 解析 tool_call
        if hasattr(response, "tool_calls") and response.tool_calls:
            tc = response.tool_calls[0]
            return ExecutorResult(
                type=SUPERVISOR_PLAN,
                payload={
                    "tool_name": tc.get("name", ""),
                    "tool_args": tc.get("args", {}),
                },
            )

        # LLM 没调工具 → 视为 respond
        text = getattr(response, "content", "") or "已完成。"
        return ExecutorResult(
            type=SUPERVISOR_PLAN,
            payload={"tool_name": "respond", "tool_args": {"text": text}},
        )
