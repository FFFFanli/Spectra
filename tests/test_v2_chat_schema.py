"""
Test that /api/v2/chat schema injection only references the user's attached tables,
NOT all tables in DuckDB. Prevents the agent from operating on the wrong table.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.api import app
    return TestClient(app)


class TestSchemaScopedToAttachedFiles:
    """Backend builds schema with full DDL of attached tables only.

    User reports: 'I uploaded users.xlsx and asked it to clean, but the agent
    cleaned daily_news / ai_2026_latest_updates instead.' Root cause: the schema
    text was so sparse the LLM picked random other tables in the DB.
    """

    def test_schema_includes_strict_scope_warning(self, client):
        """When attached_files contains a table, schema text must include explicit
        'do not query other tables' warning."""
        # Arrange: stub the runtime to capture the schema it received
        captured = {}

        class StubRuntime:
            async def run(self, user_message, thread_id, schema="", **kw):
                captured["schema"] = schema
                # Yield a quick done event so the request completes
                yield {"event": "done", "data": {"plan": {}, "artifacts": [],
                                                  "background_tasks": [],
                                                  "runtime_variant": "mtc"}}

        with patch("backend.api.TeamMTCRuntime", StubRuntime), \
             patch("backend.api.get_table_preview", create=True,
                   return_value={"columns": ["id", "name"],
                                 "rows": [[1, "x"]],
                                 "total_rows": 1}) if False else patch(
                "backend.db_utils.get_table_preview",
                return_value={"columns": ["id", "name"],
                              "rows": [[1, "x"]],
                              "total_rows": 1}):
            r = client.post("/api/v2/chat", json={
                "message": "清洗这个表",
                "thread_id": "t_schema_scope",
                "model": "deepseek-v4-flash",
                "attached_files": [
                    {"name": "users.xlsx", "table_name": "dirty_users",
                     "type": "table"},
                ],
            })
            # Drain SSE stream
            list(r.iter_lines())

        schema = captured.get("schema", "")
        # Schema must mention the attached table
        assert "dirty_users" in schema
        # Must include the strict-scope warning so LLM doesn't query other tables
        assert ("禁止查询" in schema or "只能操作" in schema or "本次任务涉及" in schema), \
            f"schema must restrict scope; got: {schema!r}"

    def test_empty_attached_files_yields_empty_schema(self, client):
        captured = {}

        class StubRuntime:
            async def run(self, user_message, thread_id, schema="", **kw):
                captured["schema"] = schema
                yield {"event": "done", "data": {"plan": {}, "artifacts": [],
                                                  "background_tasks": [],
                                                  "runtime_variant": "mtc"}}

        with patch("backend.api.TeamMTCRuntime", StubRuntime):
            r = client.post("/api/v2/chat", json={
                "message": "你好",
                "thread_id": "t_empty",
                "model": "deepseek-v4-flash",
            })
            list(r.iter_lines())

        # No attached files → empty schema (no scope warning triggered)
        assert captured.get("schema", "") == ""
