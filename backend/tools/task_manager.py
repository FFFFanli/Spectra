"""
GTD 任务管理工具：create_tasks / list_tasks / view_task / update_task /
update_task_status / delete_task / finish_task_plan。

参考 LobeChat Task + GTD 工具的 API 设计，提供持久化（SQLite）的
任务层级管理，替代原先 session-only 的 planning 工具。
"""

import json
import uuid
from langchain_core.tools import tool
from backend.state_store import (
    save_gtd_task,
    get_gtd_tasks_by_thread,
    get_gtd_task,
    update_gtd_task,
    update_gtd_task_status,
    delete_gtd_task,
    finish_all_gtd_tasks,
)

# 通过 ContextVar 注入 thread_id，避免每个工具都需要传 thread_id 参数
from contextvars import ContextVar

_thread_ctx: ContextVar[str] = ContextVar("gtd_thread_id", default="")


def set_thread_id(thread_id: str) -> None:
    _thread_ctx.set(thread_id)


def _tid() -> str:
    return _thread_ctx.get() or "default"


@tool
def create_tasks(tasks_json: str) -> str:
    """【建议在任务开始时调用】将用户需求拆解为任务列表。

    tasks_json 是 JSON 数组字符串，每个元素为：
      {"title": "任务标题", "description": "可选描述", "priority": "low|medium|high|urgent", "parent_id": "可选父任务ID"}

    支持父子层级：先创建父任务拿到 task_id，再创建子任务时传入 parent_id。
    示例: '[{"title":"探索数据","priority":"high"},{"title":"清洗数据","priority":"medium"}]'
    """
    thread_id = _tid()
    try:
        items = json.loads(tasks_json)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    if not isinstance(items, list) or len(items) == 0:
        return "Error: tasks_json 必须是非空 JSON 数组"

    created: list[dict] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return f"Error: 第 {i + 1} 个元素不是对象"
        title = str(item.get("title", "")).strip()
        if not title:
            return f"Error: 第 {i + 1} 个元素缺少 title"

        task_id = f"t{uuid.uuid4().hex[:8]}"
        save_gtd_task(
            task_id=task_id,
            thread_id=thread_id,
            title=title,
            description=str(item.get("description", "")),
            parent_id=item.get("parent_id") or None,
            status="pending",
            priority=str(item.get("priority", "medium")),
            sort_order=i,
        )
        created.append({"id": task_id, "title": title})

    lines = [f"已创建 {len(created)} 个任务："]
    for t in created:
        lines.append(f"  {t['id']}. [pending] {t['title']}")
    return "\n".join(lines)


@tool
def list_tasks(status_filter: str = "all", priority_filter: str = "all") -> str:
    """列出当前对话线程的所有任务。

    status_filter: "all" / "pending" / "in_progress" / "done" / "cancelled"
    priority_filter: "all" / "low" / "medium" / "high" / "urgent"
    """
    thread_id = _tid()
    all_tasks = get_gtd_tasks_by_thread(thread_id)
    if not all_tasks:
        return "当前没有任务。"

    # 过滤
    filtered = all_tasks
    if status_filter != "all":
        filtered = [t for t in filtered if t["status"] == status_filter]
    if priority_filter != "all":
        filtered = [t for t in filtered if t["priority"] == priority_filter]

    if not filtered:
        return f"没有匹配的任务（status={status_filter}, priority={priority_filter}）。"

    # 按层级展示：先 parent=None，再子任务缩进
    lines = [f"共 {len(filtered)} 个任务："]
    parent_ids = {t["task_id"] for t in filtered}
    for t in filtered:
        if t.get("parent_id") and t["parent_id"] in parent_ids:
            continue  # 子任务在父任务下面展示
        _format_task_tree(t, filtered, lines, indent=0)
    return "\n".join(lines)


def _format_task_tree(task: dict, all_tasks: list[dict], lines: list[str], indent: int) -> None:
    prefix = "  " * indent + ("- " if indent > 0 else "")
    status_icon = {"pending": "○", "in_progress": "◉", "done": "✓", "cancelled": "✗"}.get(
        task["status"], "?"
    )
    lines.append(
        f"{prefix}{status_icon} {task['task_id']} [{task['priority']}] {task['title']}"
    )
    children = [t for t in all_tasks if t.get("parent_id") == task["task_id"]]
    for child in children:
        _format_task_tree(child, all_tasks, lines, indent + 1)


@tool
def view_task(task_id: str) -> str:
    """查看某个任务的详细信息，包括其子任务。"""
    task = get_gtd_task(task_id)
    if not task:
        return f"未找到任务 {task_id}。"

    lines = [
        f"任务: {task['title']}",
        f"ID: {task['task_id']}",
        f"状态: {task['status']}",
        f"优先级: {task['priority']}",
        f"描述: {task['description'] or '(无)'}",
        f"备注: {task['note'] or '(无)'}",
    ]

    # 查子任务
    thread_id = _tid()
    all_tasks = get_gtd_tasks_by_thread(thread_id)
    children = [t for t in all_tasks if t.get("parent_id") == task_id]
    if children:
        lines.append(f"\n子任务 ({len(children)} 个):")
        for c in children:
            status_icon = {"pending": "○", "in_progress": "◉", "done": "✓", "cancelled": "✗"}.get(
                c["status"], "?"
            )
            lines.append(f"  {status_icon} {c['task_id']} [{c['priority']}] {c['title']}")

    return "\n".join(lines)


@tool
def update_task(task_id: str, updates_json: str) -> str:
    """更新任务属性。updates_json 是 JSON 对象，可包含字段：
    title, description, priority, status, note, parent_id。
    示例: '{"priority":"urgent","note":"客户要求优先处理"}'
    """
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON — {e}"

    if not isinstance(updates, dict) or not updates:
        return "Error: updates_json 必须是非空 JSON 对象"

    task = get_gtd_task(task_id)
    if not task:
        return f"未找到任务 {task_id}。"

    update_gtd_task(task_id, **updates)

    # 如果直接传了 status，走级联逻辑
    if "status" in updates:
        update_gtd_task_status(task_id, updates["status"])

    return f"任务 {task_id} 已更新：{json.dumps(updates, ensure_ascii=False)}"


@tool
def update_task_status(task_id: str, status: str) -> str:
    """快速更新任务状态。status 取: pending / in_progress / done / cancelled。
    当所有子任务完成后，父任务会自动标为 done。
    """
    valid = {"pending", "in_progress", "done", "cancelled"}
    if status not in valid:
        return f"Error: status 必须是 {' / '.join(valid)} 之一"

    task = get_gtd_task(task_id)
    if not task:
        return f"未找到任务 {task_id}。"

    update_gtd_task_status(task_id, status)
    return f"任务 {task_id} ({task['title']}) → {status}"


@tool
def delete_task(task_id: str) -> str:
    """删除一个任务及其所有子任务（级联删除）。"""
    task = get_gtd_task(task_id)
    if not task:
        return f"未找到任务 {task_id}。"

    deleted = delete_gtd_task(task_id)
    return f"已删除 {len(deleted)} 个任务：{', '.join(deleted)}"


@tool
def finish_task_plan(summary: str = "") -> str:
    """所有任务完成时调用。将所有未完成任务标为 done，并输出完成摘要。调用后不要再调其他工具。"""
    thread_id = _tid()
    count = finish_all_gtd_tasks(thread_id)
    if summary:
        return f"任务计划已完成（{count} 个任务已标为 done）。\n摘要：{summary}"
    return f"任务计划已完成（{count} 个任务已标为 done）。"


TASK_TOOLS = [
    create_tasks,
    list_tasks,
    view_task,
    update_task,
    update_task_status,
    delete_task,
    finish_task_plan,
]
