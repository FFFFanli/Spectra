"""
Persistence —— SQLite 持久化层。

管理 team_plans 和 agent_tasks 两张表：
  - Plan 快照写入/读取
  - Background_Task 持久化

满足：R13, R6.7
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


DB_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "data"
DB_PATH = DB_DIR / "app_state.db"


def _get_conn() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """初始化 team_plans 和 agent_tasks 表（幂等）。"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS team_plans (
                thread_id TEXT NOT NULL,
                plan_id TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (thread_id, plan_id)
            );

            CREATE TABLE IF NOT EXISTS agent_tasks (
                task_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_agent_tasks_thread ON agent_tasks(thread_id);
        """)
        conn.commit()
    finally:
        conn.close()


class PlanPersistence:
    """Plan 快照的 SQLite 持久化。"""

    def save_plan(self, snapshot: dict) -> None:
        """写入或更新 Plan 快照。"""
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO team_plans (thread_id, plan_id, steps_json, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    snapshot.get("thread_id", ""),
                    snapshot.get("plan_id", ""),
                    json.dumps(snapshot.get("steps", []), ensure_ascii=False),
                    snapshot.get("updated_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def load_plan(self, thread_id: str) -> Optional[dict]:
        """读取指定 thread 的最新 Plan 快照。"""
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM team_plans WHERE thread_id = ? ORDER BY updated_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "thread_id": row["thread_id"],
                "plan_id": row["plan_id"],
                "steps": json.loads(row["steps_json"]),
                "updated_at": row["updated_at"],
            }
        finally:
            conn.close()


class TaskPersistence:
    """Background_Task 的 SQLite 持久化。"""

    def save_task(self, task) -> None:
        """保存或更新任务记录。"""
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO agent_tasks
                   (task_id, thread_id, agent_id, title, status, result_json, created_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task.task_id,
                    task.thread_id,
                    task.agent_id,
                    task.title,
                    task.status,
                    task.result_json,
                    task.created_at,
                    task.completed_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def load_thread_tasks(self, thread_id: str) -> list[dict]:
        """查询指定 thread 的所有任务。"""
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM agent_tasks WHERE thread_id = ? ORDER BY created_at DESC",
                (thread_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def load_task(self, task_id: str) -> Optional[dict]:
        """查询单个任务。"""
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
