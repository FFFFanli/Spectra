"""
统一 Agent 规划状态 + 运行时 ContextVar 管理。

Phase 2 核心：5 个规划工具通过 ContextVar 读写当前请求的 plan 状态，
api.py 在 SSE 事件循环中读取 plan 变化并发射前端事件。
"""

from __future__ import annotations
import time
from typing import TypedDict, Annotated, Literal, Optional
from contextvars import ContextVar
from langgraph.graph.message import add_messages


# ── ContextVar：每个请求独立的 plan 运行时 ──
_plan_ctx: ContextVar[Optional[dict]] = ContextVar("current_plan", default=None)


def init_plan() -> dict:
    """初始化空 plan，返回 plan dict 并写入 ContextVar。"""
    plan = {
        "steps": [],
        "revision": 0,
        "finished": False,
        "finish_reason": "",
        "created_at": time.time(),
    }
    _plan_ctx.set(plan)
    return plan


def get_plan() -> dict | None:
    return _plan_ctx.get()


def reset_plan():
    """清除当前 plan（请求结束时调用）。"""
    _plan_ctx.set(None)


# ── 类型定义 ──

class PlanStep(TypedDict, total=False):
    id: str
    description: str
    status: Literal["pending", "running", "done", "failed"]
    note: str
    started_at: float
    finished_at: float


class PlanState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    task_goal: str
    plan: list[PlanStep]
    plan_revision: int
    tool_call_count: int
    last_tool_name: str
    max_steps: int
    max_tokens: int
    consumed_tokens: int
    artifacts: list[dict]
    chart_paths: list[str]
    report_paths: list[str]
    finished: bool
    finish_reason: str


# ── Plan 操作辅助函数（供 planning 工具使用） ──

def plan_make_steps(steps_json: str) -> str:
    """解析 JSON 数组，创建 plan steps。"""
    import json
    plan = get_plan()
    if plan is None:
        return "Error: plan not initialized"
    try:
        step_descs = json.loads(steps_json)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    if not isinstance(step_descs, list) or len(step_descs) == 0:
        return "Error: steps must be a non-empty JSON array of strings"

    steps = []
    for i, desc in enumerate(step_descs):
        steps.append({
            "id": f"s{i + 1}",
            "description": str(desc),
            "status": "running" if i == 0 else "pending",
            "note": "",
            "started_at": time.time() if i == 0 else 0,
            "finished_at": 0,
        })
    plan["steps"] = steps
    plan["_plan_created"] = True
    _plan_ctx.set(plan)
    return f"计划已创建：{len(steps)} 个步骤\n" + "\n".join(f"  {s['id']}. [{s['status']}] {s['description']}" for s in steps)


def plan_update_step(step_id: str, status: str, note: str = "") -> str:
    """更新单个步骤的状态。"""
    plan = get_plan()
    if plan is None:
        return "Error: plan not initialized"

    now = time.time()
    for s in plan["steps"]:
        if s["id"] == step_id:
            s["status"] = status
            if note:
                s["note"] = note
            if status == "running":
                s["started_at"] = now
            elif status in ("done", "failed"):
                s["finished_at"] = now
            _plan_ctx.set(plan)
            return f"步骤 {step_id} → {status}" + (f" ({note})" if note else "")
    return f"未找到步骤 {step_id}"


def plan_add_step(after_step_id: str, description: str) -> str:
    """在指定步骤后插入新步骤。"""
    plan = get_plan()
    if plan is None:
        return "Error: plan not initialized"

    insert_at = len(plan["steps"])
    for i, s in enumerate(plan["steps"]):
        if s["id"] == after_step_id:
            insert_at = i + 1
            break

    new_id = f"s{len(plan['steps']) + 1}"
    plan["steps"].insert(insert_at, {
        "id": new_id,
        "description": description,
        "status": "pending",
        "note": "",
        "started_at": 0,
        "finished_at": 0,
    })
    _plan_ctx.set(plan)
    return f"已插入步骤 {new_id}：{description}"


def plan_revise(reason: str, new_steps_json: str) -> str:
    """整体重排 plan。"""
    import json
    plan = get_plan()
    if plan is None:
        return "Error: plan not initialized"

    try:
        step_descs = json.loads(new_steps_json)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    if not isinstance(step_descs, list) or len(step_descs) == 0:
        return "Error: new_steps must be a non-empty JSON array"

    plan["revision"] += 1
    plan["_plan_revised"] = True
    plan["_revise_reason"] = reason
    plan["_consecutive_failures"] = 0  # 重排后重置失败计数

    steps = []
    for i, desc in enumerate(step_descs):
        steps.append({
            "id": f"s{i + 1}",
            "description": str(desc),
            "status": "running" if i == 0 else "pending",
            "note": "",
            "started_at": time.time() if i == 0 else 0,
            "finished_at": 0,
        })
    plan["steps"] = steps
    _plan_ctx.set(plan)
    return f"计划已重排（第 {plan['revision']} 次修订）：{reason}\n" + "\n".join(
        f"  {s['id']}. [{s['status']}] {s['description']}" for s in steps
    )


def plan_finish(summary: str = "") -> str:
    """标记任务完成。"""
    plan = get_plan()
    if plan is None:
        return "Error: plan not initialized"
    # 将所有 running 步骤标记为 done
    for s in plan["steps"]:
        if s["status"] == "running":
            s["status"] = "done"
            s["finished_at"] = time.time()
    plan["finished"] = True
    plan["finish_reason"] = "completed"
    plan["_plan_finished"] = True
    plan["_finish_summary"] = summary
    _plan_ctx.set(plan)
    return f"任务完成。{summary}" if summary else "任务完成。"


# ── 失败计数（供 single_agent 使用） ──

def plan_record_failure() -> int:
    """记录一次工具执行失败，返回连续失败次数。"""
    plan = get_plan()
    if plan is None:
        return 0
    plan["_consecutive_failures"] = plan.get("_consecutive_failures", 0) + 1
    _plan_ctx.set(plan)
    return plan["_consecutive_failures"]


def plan_reset_failures():
    """重置连续失败计数。"""
    plan = get_plan()
    if plan is not None:
        plan["_consecutive_failures"] = 0
        _plan_ctx.set(plan)


def plan_needs_revision() -> bool:
    """连续失败 ≥3 次，应触发 revise_plan。"""
    plan = get_plan()
    if plan is None:
        return False
    return plan.get("_consecutive_failures", 0) >= 3


__all__ = [
    "PlanState", "PlanStep",
    "init_plan", "get_plan", "reset_plan",
    "plan_make_steps", "plan_update_step", "plan_add_step", "plan_revise", "plan_finish",
    "plan_record_failure", "plan_reset_failures", "plan_needs_revision",
]
