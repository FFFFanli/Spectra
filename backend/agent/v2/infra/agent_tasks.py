"""
后台 Agent 任务的状态管理。使用 SQLite（state_store）持久化。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from backend.state_store import _get_connection


def _get_db():
    return _get_connection()


def init_agent_tasks_table() -> None:
    db = _get_db()
    db.execute(
        """CREATE TABLE IF NOT EXISTS agent_tasks (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            result_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            completed_at REAL
        )"""
    )
    db.commit()


def create_task(task_id: str, agent_id: str, title: str = "") -> None:
    init_agent_tasks_table()
    db = _get_db()
    db.execute(
        "INSERT INTO agent_tasks (task_id, agent_id, title, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
        (task_id, agent_id, title, time.time()),
    )
    db.commit()


def update_task(task_id: str, status: str, result: Optional[dict] = None) -> None:
    db = _get_db()
    result_json = json.dumps(result, ensure_ascii=False) if result else "{}"
    db.execute(
        "UPDATE agent_tasks SET status=?, result_json=?, completed_at=? WHERE task_id=?",
        (status, result_json, time.time(), task_id),
    )
    db.commit()


def get_task(task_id: str) -> Optional[dict]:
    db = _get_db()
    row = db.execute("SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        return None
    return {
        "task_id": row[0],
        "agent_id": row[1],
        "title": row[2],
        "status": row[3],
        "result": json.loads(row[4]) if row[4] else {},
        "created_at": row[5],
        "completed_at": row[6],
    }


def get_pending_tasks() -> list[dict]:
    init_agent_tasks_table()
    db = _get_db()
    rows = db.execute("SELECT * FROM agent_tasks WHERE status='pending' ORDER BY created_at").fetchall()
    return [
        {
            "task_id": r[0], "agent_id": r[1], "title": r[2],
            "status": r[3], "result": json.loads(r[4]) if r[4] else {},
            "created_at": r[5], "completed_at": r[6],
        }
        for r in rows
    ]
