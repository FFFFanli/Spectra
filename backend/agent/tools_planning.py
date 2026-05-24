"""
Phase 2 规划工具：make_plan / update_plan / add_step / revise_plan / finish。

这些是 LangChain @tool 函数，LLM 在任务执行过程中主动调用它们来管理任务计划。
内部通过 plan_state module 的 ContextVar 读写当前请求的 plan 运行时状态。
"""

from langchain_core.tools import tool
from backend.agent.plan_state import (
    plan_make_steps,
    plan_update_step,
    plan_add_step,
    plan_revise,
    plan_finish,
)


@tool
def make_plan(steps_json: str) -> str:
    """【强制首次调用】将任务拆解为步骤列表。steps_json 是 JSON 字符串数组，如 '["步骤1","步骤2"]'。
    对于任何非简单闲聊的请求，必须在第一轮就调用此工具制定计划。
    简单闲聊（打招呼、简单问答）不需要调用。"""
    return plan_make_steps(steps_json)


@tool
def update_plan(step_id: str, status: str, note: str = "") -> str:
    """更新某个步骤的状态。step_id 如 "s1"、"s2"。status 取 pending/running/done/failed。note 可选，补充说明原因。"""
    return plan_update_step(step_id, status, note)


@tool
def add_step(after_step_id: str, description: str) -> str:
    """在指定步骤后面插入一个新步骤。after_step_id 如 "s2"，新步骤会插入到它后面。"""
    return plan_add_step(after_step_id, description)


@tool
def revise_plan(reason: str, new_steps_json: str) -> str:
    """当当前计划行不通时，重新制定整个计划。reason 说明为什么需要重排，new_steps_json 是新的步骤 JSON 数组。"""
    return plan_revise(reason, new_steps_json)


@tool
def finish(summary: str = "") -> str:
    """任务全部完成时调用。summary 可选，给出完成摘要。调用后不要再调其他工具。"""
    return plan_finish(summary)


PLANNING_TOOLS = [make_plan, update_plan, add_step, revise_plan, finish]
