"""
SupervisorPlanner —— 纯状态机，不调 LLM。

职责：接收 ExecutorResult，返回下一步 Instruction。

设计原则（对齐 LobeHub GroupOrchestrationSupervisor）：
- decide() 完全 pure function，给定 state + result，返回 (new_state, instruction)
- 不持有任何会话外的状态
- 所有路径都能用 mock 数据触发，不需要真的调 LLM
- LLM 决策由 Runtime 在拿到 call_supervisor 指令后自行执行，再把 tool_call 结果作为
  type=supervisor_plan 的 ExecutorResult 喂回来
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

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
)


@dataclass
class Instruction:
    """状态机输出。Runtime 据此决定下一步真实动作。"""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.payload is None:
            self.payload = {}


@dataclass
class ExecutorResult:
    """Runtime 执行完一个动作后返回的结果，喂给 planner。"""

    type: str                              # INIT | SUPERVISOR_PLAN | AGENT_DONE | AGENTS_DONE | TASK_DONE | ALL_TASKS_DONE
    payload: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class SupervisorPlanner:
    """纯状态机 Supervisor。"""

    def __init__(self) -> None:
        pass

    def decide(self, state: TeamState, result: ExecutorResult) -> tuple[TeamState, Instruction]:
        """给定当前状态和执行结果，返回 (新状态, 下一步指令)。"""
        result_type = result.type

        # ── 初始 → 调 Supervisor ──
        if result_type == INIT:
            state.current_phase = CALL_SUPERVISOR
            return state, Instruction(type=CALL_SUPERVISOR, payload={
                "message": state.user_message,
                "round": state.round_count,
            })

        # ── Supervisor 决策完成 → 解析 tool_call ──
        if result_type == SUPERVISOR_PLAN:
            return self._route_supervisor_plan(state, result.payload)

        # ── 单 Agent 完成 ──
        if result_type == AGENT_DONE:
            agent_result = result.payload.get("result", {})
            agent_id = result.payload.get("agent_id", "unknown")
            state.parallel_outputs[agent_id] = agent_result
            state.round_count += 1

            # 合并 artifacts
            for art in agent_result.get("artifacts", []) if isinstance(agent_result, dict) else getattr(agent_result, "artifacts", []):
                if art not in state.artifacts:
                    state.artifacts.append(art)

            if state.round_count >= state.max_rounds:
                state.current_phase = FINISH
                return state, Instruction(type=FINISH, payload={"reason": "max_rounds"})

            state.current_phase = CALL_SUPERVISOR
            return state, Instruction(type=CALL_SUPERVISOR, payload={
                "agent_done": agent_id,
                "round": state.round_count,
                "last_result": agent_result,
            })

        # ── 并行 Agents 完成 ──
        if result_type == AGENTS_DONE:
            results = result.payload.get("results", {})
            for agent_id, agent_result in results.items():
                state.parallel_outputs[agent_id] = agent_result
                for art in agent_result.get("artifacts", []) if isinstance(agent_result, dict) else getattr(agent_result, "artifacts", []):
                    if art not in state.artifacts:
                        state.artifacts.append(art)
            state.round_count += 1

            if state.round_count >= state.max_rounds:
                state.current_phase = FINISH
                return state, Instruction(type=FINISH, payload={"reason": "max_rounds"})

            state.current_phase = CALL_SUPERVISOR
            return state, Instruction(type=CALL_SUPERVISOR, payload={
                "agents_done": list(results.keys()),
                "round": state.round_count,
            })

        # ── 后台任务完成 ──
        if result_type == TASK_DONE:
            task_id = result.payload.get("task_id", "")
            task_result = result.payload.get("result", {})
            state.background_results[task_id] = task_result
            if task_id in state.pending_tasks:
                state.pending_tasks.remove(task_id)

            if not state.pending_tasks:
                state.current_phase = CALL_SUPERVISOR
                return state, Instruction(type=ALL_TASKS_DONE, payload={
                    "results": dict(state.background_results),
                })

            # 还有其他任务在跑，继续等
            return state, Instruction(type="wait_tasks", payload={
                "remaining": len(state.pending_tasks),
            })

        # ── 所有后台任务完成 ──
        if result_type == ALL_TASKS_DONE:
            state.current_phase = CALL_SUPERVISOR
            return state, Instruction(type=CALL_SUPERVISOR, payload={
                "all_tasks_done": True,
                "results": dict(state.background_results),
            })

        # ── fallback ──
        state.current_phase = FINISH
        return state, Instruction(type=FINISH, payload={"reason": f"unknown_result_type: {result_type}"})

    def _route_supervisor_plan(self, state: TeamState, payload: dict) -> tuple[TeamState, Instruction]:
        """根据 supervisor 的 tool_call 结果路由到具体指令。"""
        tool_name = payload.get("tool_name", "")
        tool_args = payload.get("tool_args", {}) or {}

        # assign → 派单给单个 Agent
        if tool_name == "assign":
            agent_id = tool_args.get("agent_id", "")
            instruction_text = tool_args.get("instruction", "")
            state.current_phase = CALL_AGENT
            state.current_instruction = instruction_text
            return state, Instruction(type=CALL_AGENT, payload={
                "agent_id": agent_id,
                "instruction": instruction_text,
            })

        # broadcast → 并行派单
        if tool_name == "broadcast":
            agent_ids = tool_args.get("agent_ids", [])
            instruction_text = tool_args.get("instruction", "")
            state.current_phase = PARALLEL_CALL_AGENTS
            return state, Instruction(type=PARALLEL_CALL_AGENTS, payload={
                "agent_ids": agent_ids,
                "instruction": instruction_text,
            })

        # execute_task → 单个后台异步任务
        if tool_name == "execute_task":
            agent_id = tool_args.get("agent_id", "")
            title = tool_args.get("title", "")
            task = tool_args.get("task", "")
            timeout = tool_args.get("timeout", 600)
            state.current_phase = SPAWN_BACKGROUND_TASK
            return state, Instruction(type=SPAWN_BACKGROUND_TASK, payload={
                "agent_id": agent_id,
                "title": title,
                "task": task,
                "timeout": timeout,
            })

        # execute_tasks → 批量后台异步任务
        if tool_name == "execute_tasks":
            tasks = tool_args.get("tasks", [])
            state.current_phase = SPAWN_BACKGROUND_TASKS
            return state, Instruction(type=SPAWN_BACKGROUND_TASKS, payload={
                "tasks": tasks,
            })

        # respond → 直接回复
        if tool_name == "respond":
            text = tool_args.get("text", "")
            state.current_phase = REPLY_AND_FINISH
            return state, Instruction(type=REPLY_AND_FINISH, payload={
                "text": text,
            })

        # finish → 结束
        if tool_name == "finish":
            summary = tool_args.get("summary", "")
            state.current_phase = FINISH
            return state, Instruction(type=FINISH, payload={
                "summary": summary,
            })

        # 未知的工具调用 → 结束
        state.current_phase = FINISH
        return state, Instruction(type=FINISH, payload={
            "reason": f"unknown_tool: {tool_name}",
        })
