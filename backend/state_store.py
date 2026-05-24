import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import Any, Optional

from backend.app_paths import STATE_DB_PATH, ensure_directories

DB_PATH = str(STATE_DB_PATH)
TASK_TTL_SECONDS = int(os.environ.get("TASK_TTL_SECONDS", "86400"))
MAX_TASKS = int(os.environ.get("MAX_TASKS", "500"))
MAX_ALERTS = int(os.environ.get("MAX_ALERTS", "200"))

_LOCK = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_state_store() -> None:
    ensure_directories()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                thread_id TEXT,
                status TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                time_text TEXT NOT NULL,
                prompt TEXT NOT NULL,
                report TEXT NOT NULL,
                charts_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_expires_at ON tasks(expires_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at)"
        )
        init_gtd_tasks(conn)
        init_cron_jobs(conn)
        _cleanup_tasks(conn)
        _trim_table(conn, "tasks", "task_id", "updated_at", MAX_TASKS)
        _trim_table(conn, "alerts", "alert_id", "created_at", MAX_ALERTS)
        conn.commit()


def _cleanup_tasks(conn: sqlite3.Connection) -> None:
    now_ts = int(time.time())
    conn.execute("DELETE FROM tasks WHERE expires_at <= ?", (now_ts,))


def _trim_table(
    conn: sqlite3.Connection,
    table_name: str,
    id_column: str,
    order_column: str,
    max_rows: int,
) -> None:
    if max_rows <= 0:
        return

    count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    excess = count - max_rows
    if excess <= 0:
        return

    rows = conn.execute(
        f"SELECT {id_column} FROM {table_name} ORDER BY {order_column} ASC LIMIT ?",
        (excess,),
    ).fetchall()
    ids_to_delete = [row[id_column] for row in rows]
    if not ids_to_delete:
        return

    placeholders = ",".join("?" for _ in ids_to_delete)
    conn.execute(
        f"DELETE FROM {table_name} WHERE {id_column} IN ({placeholders})",
        ids_to_delete,
    )


def create_task(task_id: str, thread_id: str, ttl_seconds: int = TASK_TTL_SECONDS) -> None:
    now_ts = int(time.time())
    expires_at = now_ts + max(ttl_seconds, 1)
    with _LOCK, _get_connection() as conn:
        _cleanup_tasks(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO tasks (
                task_id, thread_id, status, result_json, error, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, NULL, NULL, ?, ?, ?)
            """,
            (task_id, thread_id, "running", now_ts, now_ts, expires_at),
        )
        _trim_table(conn, "tasks", "task_id", "updated_at", MAX_TASKS)
        conn.commit()


def complete_task(task_id: str, result: dict[str, Any]) -> None:
    now_ts = int(time.time())
    with _LOCK, _get_connection() as conn:
        row = conn.execute(
            "SELECT created_at, expires_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        created_at = row["created_at"] if row else now_ts
        expires_at = row["expires_at"] if row else now_ts + TASK_TTL_SECONDS
        conn.execute(
            """
            INSERT OR REPLACE INTO tasks (
                task_id, thread_id, status, result_json, error, created_at, updated_at, expires_at
            ) VALUES (
                ?,
                COALESCE((SELECT thread_id FROM tasks WHERE task_id = ?), NULL),
                ?,
                ?,
                NULL,
                ?,
                ?,
                ?
            )
            """,
            (
                task_id,
                task_id,
                "completed",
                json.dumps(result, ensure_ascii=False),
                created_at,
                now_ts,
                expires_at,
            ),
        )
        _cleanup_tasks(conn)
        _trim_table(conn, "tasks", "task_id", "updated_at", MAX_TASKS)
        conn.commit()


def fail_task(task_id: str, error: str) -> None:
    now_ts = int(time.time())
    with _LOCK, _get_connection() as conn:
        row = conn.execute(
            "SELECT created_at, expires_at FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        created_at = row["created_at"] if row else now_ts
        expires_at = row["expires_at"] if row else now_ts + TASK_TTL_SECONDS
        conn.execute(
            """
            INSERT OR REPLACE INTO tasks (
                task_id, thread_id, status, result_json, error, created_at, updated_at, expires_at
            ) VALUES (
                ?,
                COALESCE((SELECT thread_id FROM tasks WHERE task_id = ?), NULL),
                ?,
                NULL,
                ?,
                ?,
                ?,
                ?
            )
            """,
            (
                task_id,
                task_id,
                "error",
                error,
                created_at,
                now_ts,
                expires_at,
            ),
        )
        _cleanup_tasks(conn)
        _trim_table(conn, "tasks", "task_id", "updated_at", MAX_TASKS)
        conn.commit()


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        _cleanup_tasks(conn)
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            conn.commit()
            return None

        conn.commit()

    payload: dict[str, Any] = {"status": row["status"]}
    if row["status"] == "completed" and row["result_json"]:
        payload["result"] = json.loads(row["result_json"])
    if row["status"] == "error":
        payload["error"] = row["error"] or "Unknown error"
    return payload


# ── GTD 任务管理 ──

MAX_GTD_TASKS = int(os.environ.get("MAX_GTD_TASKS", "1000"))


def init_gtd_tasks(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gtd_tasks (
            task_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            parent_id TEXT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            priority TEXT DEFAULT 'medium',
            sort_order INTEGER DEFAULT 0,
            note TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtd_thread ON gtd_tasks(thread_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_gtd_parent ON gtd_tasks(parent_id)"
    )


def save_gtd_task(
    task_id: str,
    thread_id: str,
    title: str,
    description: str = "",
    parent_id: str | None = None,
    status: str = "pending",
    priority: str = "medium",
    sort_order: int = 0,
    note: str = "",
) -> None:
    now_ts = time.time()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO gtd_tasks (
                task_id, thread_id, parent_id, title, description,
                status, priority, sort_order, note, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM gtd_tasks WHERE task_id = ?), ?),
                ?
            )
            """,
            (
                task_id, thread_id, parent_id, title, description,
                status, priority, sort_order, note,
                task_id, now_ts, now_ts,
            ),
        )
        _trim_table(conn, "gtd_tasks", "task_id", "updated_at", MAX_GTD_TASKS)
        conn.commit()


def get_gtd_tasks_by_thread(thread_id: str) -> list[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM gtd_tasks WHERE thread_id = ? ORDER BY sort_order ASC, created_at ASC",
            (thread_id,),
        ).fetchall()
        conn.commit()
    return [dict(row) for row in rows]


def get_gtd_task(task_id: str) -> dict[str, Any] | None:
    with _LOCK, _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM gtd_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        conn.commit()
    return dict(row) if row else None


def update_gtd_task(task_id: str, **fields) -> None:
    allowed = {"title", "description", "status", "priority", "sort_order", "note", "parent_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]
    with _LOCK, _get_connection() as conn:
        conn.execute(
            f"UPDATE gtd_tasks SET {set_clause} WHERE task_id = ?", values
        )
        conn.commit()


def update_gtd_task_status(task_id: str, status: str) -> None:
    now_ts = time.time()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            "UPDATE gtd_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, now_ts, task_id),
        )
        # 检查父任务：如果所有子任务都 done，自动把父任务标为 done
        row = conn.execute(
            "SELECT parent_id FROM gtd_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row and row["parent_id"]:
            parent_id = row["parent_id"]
            pending = conn.execute(
                "SELECT COUNT(*) FROM gtd_tasks WHERE parent_id = ? AND status != 'done' AND status != 'cancelled'",
                (parent_id,),
            ).fetchone()[0]
            if pending == 0:
                conn.execute(
                    "UPDATE gtd_tasks SET status = 'done', updated_at = ? WHERE task_id = ?",
                    (now_ts, parent_id),
                )
        conn.commit()


def delete_gtd_task(task_id: str) -> list[str]:
    """删除任务及其所有子孙任务，返回被删除的 task_id 列表。"""
    with _LOCK, _get_connection() as conn:
        # 递归收集所有子孙
        deleted = [task_id]
        queue = [task_id]
        while queue:
            pid = queue.pop()
            children = conn.execute(
                "SELECT task_id FROM gtd_tasks WHERE parent_id = ?", (pid,)
            ).fetchall()
            for c in children:
                deleted.append(c["task_id"])
                queue.append(c["task_id"])
        placeholders = ",".join("?" for _ in deleted)
        conn.execute(
            f"DELETE FROM gtd_tasks WHERE task_id IN ({placeholders})", deleted
        )
        conn.commit()
    return deleted


def finish_all_gtd_tasks(thread_id: str) -> int:
    """将 thread 下所有未完成的任务标为 done，返回更新数量。"""
    now_ts = time.time()
    with _LOCK, _get_connection() as conn:
        cur = conn.execute(
            "UPDATE gtd_tasks SET status = 'done', updated_at = ? "
            "WHERE thread_id = ? AND status NOT IN ('done', 'cancelled')",
            (now_ts, thread_id),
        )
        conn.commit()
        return cur.rowcount


def add_alert(
    *,
    alert_id: str,
    prompt: str,
    report: str,
    charts: list[str],
    time_text: Optional[str] = None,
) -> None:
    now_ts = int(time.time())
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO alerts (
                alert_id, time_text, prompt, report, charts_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                time_text or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                prompt,
                report,
                json.dumps(charts, ensure_ascii=False),
                now_ts,
            ),
        )
        _trim_table(conn, "alerts", "alert_id", "created_at", MAX_ALERTS)
        conn.commit()


# ── 定时任务 (Cron) ──

MAX_CRON_JOBS = int(os.environ.get("MAX_CRON_JOBS", "50"))


def init_cron_jobs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cron_jobs (
            job_id TEXT PRIMARY KEY,
            cron_expr TEXT NOT NULL,
            prompt TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cron_status ON cron_jobs(status)"
    )


def save_cron_job(job_id: str, cron_expr: str, prompt: str, status: str = "active") -> None:
    now_ts = time.time()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO cron_jobs (
                job_id, cron_expr, prompt, status, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?,
                COALESCE((SELECT created_at FROM cron_jobs WHERE job_id = ?), ?),
                ?
            )
            """,
            (job_id, cron_expr, prompt, status, job_id, now_ts, now_ts),
        )
        _trim_table(conn, "cron_jobs", "job_id", "updated_at", MAX_CRON_JOBS)
        conn.commit()


def list_cron_jobs(status_filter: str = "all") -> list[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        if status_filter == "all":
            rows = conn.execute(
                "SELECT * FROM cron_jobs ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cron_jobs WHERE status = ? ORDER BY created_at DESC",
                (status_filter,),
            ).fetchall()
        conn.commit()
    return [dict(row) for row in rows]


def get_cron_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK, _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM cron_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        conn.commit()
    return dict(row) if row else None


def update_cron_job_status(job_id: str, status: str) -> None:
    now_ts = time.time()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            "UPDATE cron_jobs SET status = ?, updated_at = ? WHERE job_id = ?",
            (status, now_ts, job_id),
        )
        conn.commit()


def delete_cron_job(job_id: str) -> bool:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("DELETE FROM cron_jobs WHERE job_id = ?", (job_id,))
        conn.commit()
        return cur.rowcount > 0


def get_active_cron_jobs() -> list[dict[str, Any]]:
    return list_cron_jobs(status_filter="active")


def list_alerts(limit: int = MAX_ALERTS) -> list[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        _trim_table(conn, "alerts", "alert_id", "created_at", MAX_ALERTS)
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?",
            (max(limit, 1),),
        ).fetchall()
        conn.commit()

    alerts = []
    for row in rows:
        alerts.append(
            {
                "id": row["alert_id"],
                "time": row["time_text"],
                "prompt": row["prompt"],
                "report": row["report"],
                "charts": json.loads(row["charts_json"]),
            }
        )
    return alerts
