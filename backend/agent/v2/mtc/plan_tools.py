"""
Plan LLM 工具定义 —— 供 LLM 调用的 Plan 操作工具集。

工具列表：make_plan / update_plan / add_step / revise_plan / finish / broadcast / execute_task / execute_tasks

满足：R3, R5.5, R6
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool


# 这些工具由 PlanManager 实例的状态驱动，实际调用时通过 partial 或闭包绑定
# 全局的 tool 定义仅用于 schema 声明，执行逻辑在 runtime 中绑定


@tool
def make_plan(steps: list[dict]) -> str:
    """创建任务执行计划。

    Args:
        steps: 有序步骤数组，每项包含:
            - description (str): 步骤描述
            - assignee_agent_id (str): 执行者，可选值: coder/writer/researcher/responder/designer/reviewer
            - dependencies (list[str], 可选): 依赖的步骤索引列表
    """
    # 实际逻辑由 runtime 绑定，此占位供 schema 生成
    return ""


@tool
def update_plan(step_id: str, status: str, note: str = "") -> str:
    """更新某个步骤的状态。

    Args:
        step_id: 步骤 ID
        status: 新状态，可选值: running/completed/failed/skipped
        note: 可选的备注说明
    """
    return ""


@tool
def add_step(after_step_id: str, description: str, assignee_agent_id: str) -> str:
    """在指定步骤之后插入新步骤。

    Args:
        after_step_id: 插入位置（在此步骤之后）
        description: 新步骤描述
        assignee_agent_id: 执行者 agent_id
    """
    return ""


@tool
def revise_plan(reason: str, new_steps: list[dict]) -> str:
    """重排剩余 Plan 步骤（保留已完成的步骤不变）。

    Args:
        reason: 重排原因
        new_steps: 新的步骤数组，格式同 make_plan 的 steps 参数
    """
    return ""


@tool
def finish(summary: str) -> str:
    """结束当前 Plan，将所有未完成步骤标记为 skipped。

    Args:
        summary: 任务完成摘要
    """
    return ""


@tool
def broadcast(agent_ids: list[str], instruction: str) -> str:
    """向多个 Agent 同时发送指令，生成 N 条并行步骤。

    Args:
        agent_ids: 目标 agent_id 列表
        instruction: 统一指令内容
    """
    return ""


@tool
def execute_task(agent_id: str, title: str, task: str, timeout: int = 600) -> str:
    """提交后台异步任务，立即返回 task_id，不阻塞主 Plan。

    Args:
        agent_id: 执行任务的 agent
        title: 任务标题（前端展示用）
        task: 任务详细描述
        timeout: 超时秒数（默认 600）
    """
    return ""


@tool
def execute_tasks(tasks: list[dict]) -> str:
    """批量提交后台异步任务。

    Args:
        tasks: 任务数组，每项含 agent_id/title/task/timeout 字段
    """
    return ""


# 供首次 LLM 调用（Plan 创建阶段）—— 仅 make_plan
PLAN_CREATION_TOOLS = [make_plan]

# 供 Plan 执行期间的 LLM 调用（如失败重排时）
PLAN_EXECUTION_TOOLS = [update_plan, add_step, revise_plan, finish, broadcast]

# 所有工具（供 runtime 注册）
ALL_PLAN_TOOLS = [make_plan, update_plan, add_step, revise_plan, finish, broadcast, execute_task, execute_tasks]
