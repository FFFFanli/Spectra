"""
BackgroundTaskManager —— 后台异步任务管理。

线程池容量 4，超时 600s，支持跨请求快照查询。
持久化到 SQLite agent_tasks 表。

满足：R6
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


@dataclass
class BackgroundTask:
    task_id: str
    thread_id: str
    agent_id: str
    title: str
    task: str
    timeout: int = 600
    status: str = "pending"  # pending|running|completed|failed
    result_json: str = ""
    created_at: str = ""
    completed_at: str = ""
    progress_notes: list[dict] = field(default_factory=list)


class BackgroundTaskManager:
    POOL_SIZE = 4
    DEFAULT_TIMEOUT = 600

    def __init__(self, persistence=None):
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.POOL_SIZE)
        self._tasks: dict[str, BackgroundTask] = {}
        self._emit_fn: Optional[Callable] = None
        self._persistence = persistence
        self._execute_fn: Optional[Callable] = None  # (agent_id, task_desc, thread_id) -> dict

    def set_emit_fn(self, emit_fn: Callable[[str, dict], None]) -> None:
        self._emit_fn = emit_fn

    def set_execute_fn(self, fn: Callable) -> None:
        """注册后台任务的实际执行函数。fn(agent_id, task_desc, thread_id) -> dict。"""
        self._execute_fn = fn

    def submit(
        self,
        agent_id: str,
        title: str,
        task: str,
        timeout: int = 600,
        thread_id: str = "",
    ) -> str:
        """提交后台任务，立即返回 task_id。"""
        task_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()

        bg_task = BackgroundTask(
            task_id=task_id,
            thread_id=thread_id,
            agent_id=agent_id,
            title=title,
            task=task,
            timeout=timeout or self.DEFAULT_TIMEOUT,
            status="pending",
            created_at=now,
        )
        self._tasks[task_id] = bg_task

        # Persist
        if self._persistence:
            try:
                self._persistence.save_task(bg_task)
            except Exception:
                pass

        # Emit task_pending
        if self._emit_fn:
            self._emit_fn("task_pending", {
                "task_id": task_id,
                "agent_id": agent_id,
                "title": title,
                "status": "pending",
            })

        # Submit to thread pool
        self._executor.submit(self._run_task, bg_task)

        return task_id

    def _run_task(self, bg_task: BackgroundTask) -> None:
        """在线程池中执行任务，含超时强制中断。

        在单独的线程中执行 execute_fn，主线程 join(timeout) 等待。
        超时后标记失败（后台线程会继续运行直到自行结束，但结果被丢弃）。
        """
        import threading

        bg_task.status = "running"
        self._emit_progress(bg_task.task_id, "running", "任务开始执行")
        start_time = time.time()

        if self._execute_fn is None:
            self.fail_task(bg_task.task_id, "未注册后台任务执行函数")
            return

        result_container = {"result": None, "error": None, "done": False}

        def _target():
            try:
                result_container["result"] = self._execute_fn(
                    bg_task.agent_id, bg_task.task, bg_task.thread_id
                )
            except Exception as exc:
                result_container["error"] = str(exc)
            result_container["done"] = True

        worker = threading.Thread(target=_target, daemon=True)
        worker.start()
        worker.join(timeout=bg_task.timeout)

        if not result_container["done"]:
            elapsed = time.time() - start_time
            self.fail_task(
                bg_task.task_id,
                f"任务超时 (timeout={bg_task.timeout}s, elapsed={elapsed:.1f}s)",
            )
            return

        if result_container["error"]:
            self.fail_task(bg_task.task_id, result_container["error"])
            return

        elapsed = time.time() - start_time
        self._emit_progress(bg_task.task_id, "running",
                           f"执行完成，耗时 {elapsed:.1f}s")
        self.complete_task(bg_task.task_id, result_container["result"])

    def _emit_progress(self, task_id: str, status: str, note: str) -> None:
        """发送 task_progress 事件。"""
        if task_id in self._tasks:
            self._tasks[task_id].progress_notes.append({
                "status": status,
                "note": note,
                "time": datetime.now(timezone.utc).isoformat(),
            })
        if self._emit_fn:
            self._emit_fn("task_progress", {
                "task_id": task_id,
                "status": status,
                "note": note,
            })

    def complete_task(self, task_id: str, result: dict) -> None:
        """标记任务完成。"""
        if task_id not in self._tasks:
            return
        bg_task = self._tasks[task_id]
        bg_task.status = "ok" if result.get("status") == "ok" else "failed"
        bg_task.completed_at = datetime.now(timezone.utc).isoformat()
        bg_task.result_json = result.get("reply", "")

        import json
        if self._persistence:
            try:
                self._persistence.save_task(bg_task)
            except Exception:
                pass

        if self._emit_fn:
            self._emit_fn("task_completed", {
                "task_id": task_id,
                "status": bg_task.status,
                "artifacts": result.get("artifacts", []),
                "reply": result.get("reply", ""),
            })

    def fail_task(self, task_id: str, error: str) -> None:
        """标记任务失败。"""
        if task_id not in self._tasks:
            return
        bg_task = self._tasks[task_id]
        bg_task.status = "failed"
        bg_task.completed_at = datetime.now(timezone.utc).isoformat()

        if self._persistence:
            try:
                self._persistence.save_task(bg_task)
            except Exception:
                pass

        if self._emit_fn:
            self._emit_fn("task_failed", {
                "task_id": task_id,
                "error": error,
            })

    def get_status(self, task_id: str) -> Optional[dict]:
        """查询单个任务状态。"""
        if task_id not in self._tasks:
            return None
        t = self._tasks[task_id]
        return {
            "task_id": t.task_id,
            "agent_id": t.agent_id,
            "title": t.title,
            "status": t.status,
            "created_at": t.created_at,
            "completed_at": t.completed_at,
        }

    def get_thread_tasks(self, thread_id: str) -> list[dict]:
        """查询某个 thread 的所有任务。"""
        return [
            {
                "task_id": t.task_id,
                "agent_id": t.agent_id,
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at,
                "completed_at": t.completed_at,
            }
            for t in self._tasks.values()
            if t.thread_id == thread_id
        ]

    def shutdown(self) -> None:
        """关闭线程池。"""
        self._executor.shutdown(wait=False)
