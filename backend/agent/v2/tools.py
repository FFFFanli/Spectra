"""
Supervisor 工具集 —— 6 个 LangChain @tool，对齐 LobeHub GroupChat 的 assign/broadcast/...
"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
def assign(agent_id: str, instruction: str) -> str:
    """派单一同步任务给单个成员 Agent。

    Args:
        agent_id: 成员 ID，可选 coder / writer / researcher / responder
        instruction: 发送给该成员的子指令，描述它要完成的具体任务
    """
    return f"已派单给 {agent_id}：{instruction}"


@tool
def broadcast(agent_ids: list[str], instruction: str) -> str:
    """并行派发同一指令给多个成员 Agent，各成员独立执行后合并结果。

    Args:
        agent_ids: 成员 ID 列表，如 ["coder", "researcher"]
        instruction: 发送给所有成员的任务描述
    """
    agents = ", ".join(agent_ids)
    return f"已广播给 {agents}：{instruction}"


@tool
def execute_task(agent_id: str, title: str, task: str, timeout: int = 600) -> str:
    """派发后台异步长任务给单个成员。不阻塞主对话，完成后自动通知。

    Args:
        agent_id: 成员 ID
        title: 任务标题（用于前端展示）
        task: 完整的任务描述
        timeout: 超时秒数，默认 600
    """
    return f"已创建后台任务 [{title}] 派给 {agent_id}，超时 {timeout}s"


@tool
def execute_tasks(tasks: list[dict]) -> str:
    """批量派发多个后台异步任务，可并行执行。

    Args:
        tasks: 任务列表，每项格式 {"agent_id": "...", "title": "...", "task": "..."}
    """
    count = len(tasks)
    return f"已批量创建 {count} 个后台任务"


@tool
def respond(text: str) -> str:
    """Supervisor 直接回答用户，不派单给任何成员。用于闲聊、概念解释等无需数据/报告的场景。

    Args:
        text: 直接返回给用户的回答内容
    """
    return f"直接回复：{text}"


@tool
def finish(summary: str) -> str:
    """标记任务完成，所有必要工作已结束。

    Args:
        summary: 任务完成摘要
    """
    return f"任务完成：{summary}"


SUPERVISOR_TOOLS = [assign, broadcast, execute_task, execute_tasks, respond, finish]
