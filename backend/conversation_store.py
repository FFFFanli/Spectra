"""
对话历史服务端持久化。

存到与 task/alert 同一个 SQLite (data/app_state.db) 里，新增 conversations 表。
前端调用 REST 接口读写，本机多浏览器/换机/换 profile 都能看到同一份历史。

为多用户场景预留 user_id 字段：当前所有写入都填默认值 "default"，
后续接入登录后只需把 user_id 替换为真实身份即可。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Optional

from backend.app_paths import STATE_DB_PATH, ensure_directories

DB_PATH = str(STATE_DB_PATH)
DEFAULT_USER_ID = "default"
MAX_CONVERSATIONS_PER_USER = 500

_LOCK = threading.Lock()


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_conversation_store() -> None:
    ensure_directories()
    with _LOCK, _get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                thread_id TEXT,
                title TEXT,
                messages_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_user_updated ON conversations(user_id, updated_at DESC)"
        )
        conn.commit()


def _trim_user_history(conn: sqlite3.Connection, user_id: str) -> None:
    """同一用户最多保留 MAX_CONVERSATIONS_PER_USER 条，按 updated_at 老旧顺序裁剪。"""
    if MAX_CONVERSATIONS_PER_USER <= 0:
        return
    count = conn.execute(
        "SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    excess = count - MAX_CONVERSATIONS_PER_USER
    if excess <= 0:
        return
    rows = conn.execute(
        "SELECT id FROM conversations WHERE user_id = ? ORDER BY updated_at ASC LIMIT ?",
        (user_id, excess),
    ).fetchall()
    ids = [row["id"] for row in rows]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM conversations WHERE id IN ({placeholders})", ids)


def list_conversations(user_id: str = DEFAULT_USER_ID, *, limit: int = 200) -> list[dict[str, Any]]:
    """列表只返回元数据，不带 messages，避免大对话拖慢列表页加载。"""
    with _LOCK, _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, thread_id, title, created_at, updated_at
            FROM conversations
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, max(limit, 1)),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "threadId": r["thread_id"],
            "title": r["title"] or "空对话",
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]


def get_conversation(conv_id: str, user_id: str = DEFAULT_USER_ID) -> Optional[dict[str, Any]]:
    with _LOCK, _get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
    if not row:
        return None
    try:
        messages = json.loads(row["messages_json"]) if row["messages_json"] else []
    except json.JSONDecodeError:
        messages = []
    return {
        "id": row["id"],
        "threadId": row["thread_id"],
        "title": row["title"],
        "messages": messages,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def upsert_conversation(
    *,
    conv_id: str,
    thread_id: str,
    title: str,
    messages: list[dict[str, Any]],
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """新增或覆盖一条对话；若不存在则按当前时间填 created_at。"""
    now_ts = int(time.time())
    payload = json.dumps(messages, ensure_ascii=False)
    with _LOCK, _get_connection() as conn:
        existing = conn.execute(
            "SELECT created_at FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        ).fetchone()
        created_at = existing["created_at"] if existing else now_ts
        conn.execute(
            """
            INSERT OR REPLACE INTO conversations (
                id, user_id, thread_id, title, messages_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (conv_id, user_id, thread_id, title, payload, created_at, now_ts),
        )
        _trim_user_history(conn, user_id)
        conn.commit()
    return {
        "id": conv_id,
        "threadId": thread_id,
        "title": title,
        "createdAt": created_at,
        "updatedAt": now_ts,
    }


def delete_conversation(conv_id: str, user_id: str = DEFAULT_USER_ID) -> bool:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conv_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0


def clear_conversations(user_id: str = DEFAULT_USER_ID) -> int:
    with _LOCK, _get_connection() as conn:
        cur = conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()
        return cur.rowcount
