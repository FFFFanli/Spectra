"""
后台任务派发的线程池封装。

所有 execute_task / execute_tasks 最终都通过此模块落入 daemon 线程，
确保不阻塞主 asyncio 事件循环。
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Callable, Optional

_agent_thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-task")


def spawn_agent_task(
    agent_id: str,
    title: str,
    task_fn: Callable[..., Any],
    *args: Any,
    on_done: Optional[Callable[[dict], None]] = None,
    **kwargs: Any,
) -> str:
    """在后台线程池中执行 task_fn，返回 task_id。

    task_fn 会在独立线程中运行，完成后可选回调 on_done。
    """
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    def _runner() -> None:
        try:
            result = task_fn(*args, **kwargs)
            if on_done:
                on_done({"task_id": task_id, "agent_id": agent_id, "status": "ok", "result": result})
        except Exception as exc:
            if on_done:
                on_done({"task_id": task_id, "agent_id": agent_id, "status": "failed", "error": str(exc)})

    _agent_thread_pool.submit(_runner)
    return task_id


def get_thread_pool() -> ThreadPoolExecutor:
    return _agent_thread_pool
