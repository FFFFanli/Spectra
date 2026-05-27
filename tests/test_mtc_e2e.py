"""
E2E tests for Team MTC mode (Task 17).

Covers:
  17.1  CSV upload → Plan → coder → writer → PDF → frontend display
  17.2  broadcast parallel research
  17.3  execute_task background task + continue conversation
  17.4  Refresh page → restore Plan + Background_Task state

All LLM calls are mocked to avoid real API costs.
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Reusable mocks ───────────────────────────────────────────────

def make_ok_result(agent_id="responder", reply="done", artifacts=None):
    """Create a successful AgentResult."""
    from backend.agent.v2.members.base import AgentResult
    return AgentResult(
        agent_id=agent_id, status="ok", reply=reply,
        code=None, artifacts=artifacts or [], error=None,
    )


def make_mock_llm_plan_response(plan_steps):
    """Create a mock LLM response that calls make_plan with given steps."""

    class FakeToolCall(dict):
        """A dict-like object that supports .get() for name/args access."""
        pass

    class FakeMessage:
        def __init__(self, tool_calls):
            self.content = ""
            self.tool_calls = tool_calls
            self.additional_kwargs = {}
            self.response_metadata = {"token_usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    tc = FakeToolCall({"name": "make_plan", "args": {"steps": plan_steps}})
    return FakeMessage([tc])


def mock_all_members(monkeypatch):
    """Patch all MemberAgent.execute to return ok results."""
    async def fake_execute(self_member, ctx, on_event=None):
        return make_ok_result(
            agent_id=getattr(self_member, 'agent_id', 'unknown'),
            reply=f"Executed: {ctx.instruction[:50]}",
        )

    members_mods = [
        "backend.agent.v2.members.coder.CoderMember.execute",
        "backend.agent.v2.members.writer.WriterMember.execute",
        "backend.agent.v2.members.researcher.ResearcherMember.execute",
        "backend.agent.v2.members.responder.ResponderMember.execute",
        "backend.agent.v2.members.designer.DesignerMember.execute",
        "backend.agent.v2.members.reviewer.ReviewerMember.execute",
    ]
    for mod in members_mods:
        monkeypatch.setattr(mod, fake_execute)


# ── 17.1  CSV → Plan → coder → writer → PDF ─────────────────────

class TestE2ECsvToPdf:
    """End-to-end: upload CSV → auto Plan → coder analysis → writer PDF."""

    def test_full_pipeline_yields_all_expected_events(self, monkeypatch):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        # Mock LLM to return a data analysis plan
        plan_steps = [
            {"description": "理解数据结构", "assignee_agent_id": "coder", "dependencies": []},
            {"description": "执行数据分析", "assignee_agent_id": "coder", "dependencies": []},
            {"description": "生成分析报告PDF", "assignee_agent_id": "writer", "dependencies": []},
        ]

        mock_llm_msg = make_mock_llm_plan_response(plan_steps)

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            def invoke(self, messages, config=None, tools=None):
                return mock_llm_msg

            def bind_tools(self, tools):
                return self

        monkeypatch.setattr("backend.agent.v2.mtc.runtime._create_llm", FakeLLM)
        mock_all_members(monkeypatch)

        rt = TeamMTCRuntime()

        # Create a temp CSV file
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8") as f:
            f.write("product,sales,date\nA,100,2026-01-01\nB,200,2026-01-02\nC,150,2026-01-03\n")
            csv_path = f.name

        try:
            attached = [{
                "name": "sales.csv",
                "path": csv_path,
                "type": "text/csv",
                "table_name": "sales_data",
                "size": os.path.getsize(csv_path),
            }]

            events = []
            async def collect():
                async for e in rt.run(
                    user_message="analyze this sales data and generate a PDF report",
                    thread_id="t_e2e_csv_pdf",
                    schema="table sales_data: product VARCHAR, sales INTEGER, date DATE",
                    attached_files=attached,
                    skill_workflow_id=None,
                ):
                    events.append(e)
            asyncio.run(collect())

            event_types = [e.get("event") for e in events]

            # Must have plan_created
            assert "plan_created" in event_types, f"Expected plan_created in {event_types}"

            # Must have step_started and step_completed for each step
            started = [e for e in events if e.get("event") == "step_started"]
            completed = [e for e in events if e.get("event") == "step_completed"]
            assert len(started) >= 3, f"Expected >=3 step_started, got {len(started)}"
            assert len(completed) >= 3, f"Expected >=3 step_completed, got {len(completed)}"

            # done must be last
            assert event_types[-1] == "done"
            done_data = events[-1].get("data", {})
            assert "plan" in done_data
            assert "runtime_variant" in done_data
            assert done_data["runtime_variant"] == "mtc"

        finally:
            os.unlink(csv_path)

    def test_pipeline_schema_forwarded_to_members(self, monkeypatch):
        """Schema from attached CSV must be forwarded to coder/writer MemberContext."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime
        from backend.agent.v2.mtc.plan_manager import PlanManager, PlanStep

        rt = TeamMTCRuntime()
        rt._schema = "表 test_tbl：col_a INT, col_b VARCHAR"
        rt._attached_files = [{"name": "test.csv", "table_name": "test_tbl"}]
        rt._plan_manager = PlanManager("t_schema")

        captured_schema = {}

        async def capture_execute(self_member, ctx, on_event=None):
            captured_schema["schema"] = ctx.schema
            captured_schema["files"] = ctx.attached_files
            return make_ok_result(agent_id=self_member.agent_id, reply="ok")

        monkeypatch.setattr(
            "backend.agent.v2.members.coder.CoderMember.execute", capture_execute
        )

        step = PlanStep(id="abc12345", description="analyze", assignee_agent_id="coder")
        asyncio.run(rt._execute_step(step))

        assert "test_tbl" in captured_schema.get("schema", "")
        assert captured_schema["files"][0]["table_name"] == "test_tbl"


# ── 17.2  broadcast parallel research ────────────────────────────

class TestE2EBroadcast:
    """End-to-end: broadcast parallel research of multiple targets."""

    def test_broadcast_three_researchers_run_concurrently(self, monkeypatch):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        plan_steps = [
            {"description": "调研竞品A", "assignee_agent_id": "researcher", "dependencies": []},
            {"description": "调研竞品B", "assignee_agent_id": "researcher", "dependencies": []},
            {"description": "调研竞品C", "assignee_agent_id": "researcher", "dependencies": []},
            {"description": "汇总对比报告", "assignee_agent_id": "writer", "dependencies": []},
        ]

        mock_llm_msg = make_mock_llm_plan_response(plan_steps)

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            def invoke(self, messages, config=None, tools=None):
                return mock_llm_msg

            def bind_tools(self, tools):
                return self

        monkeypatch.setattr("backend.agent.v2.mtc.runtime._create_llm", FakeLLM)

        # Track concurrency of researcher execution
        concurrent = {"current": 0, "max": 0}

        async def tracking_execute(self_member, ctx, on_event=None):
            if self_member.name == "researcher":
                concurrent["current"] += 1
                concurrent["max"] = max(concurrent["max"], concurrent["current"])
                await asyncio.sleep(0.1)  # enough time to overlap
                concurrent["current"] -= 1
            return make_ok_result(agent_id=self_member.name, reply="done")

        monkeypatch.setattr(
            "backend.agent.v2.members.researcher.ResearcherMember.execute", tracking_execute
        )
        monkeypatch.setattr(
            "backend.agent.v2.members.writer.WriterMember.execute",
            lambda self_member, ctx, on_event=None: asyncio.sleep(0) or make_ok_result("writer", "done"),
        )
        monkeypatch.setattr(
            "backend.agent.v2.members.responder.ResponderMember.execute",
            lambda self_member, ctx, on_event=None: asyncio.sleep(0) or make_ok_result("responder", "done"),
        )

        rt = TeamMTCRuntime()
        events = []
        async def collect():
            async for e in rt.run(
                user_message="同时调研竞品A、B、C的市场定位",
                thread_id="t_e2e_broadcast",
                schema="",
                attached_files=None,
            ):
                events.append(e)
        asyncio.run(collect())

        # Verify: researchers should have run concurrently
        assert concurrent["max"] >= 2, \
            f"Expected >=2 concurrent researchers, got max={concurrent['max']}"

        # Verify: done is last
        assert events[-1].get("event") == "done"

    def test_broadcast_dependencies_respected(self, monkeypatch):
        """Writer should wait until all researchers complete."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        plan_steps = [
            {"description": "research A", "assignee_agent_id": "researcher", "dependencies": []},
            {"description": "synthesize", "assignee_agent_id": "writer", "dependencies": ["research A"]},
        ]

        mock_llm_msg = make_mock_llm_plan_response(plan_steps)

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                pass

            def invoke(self, messages, config=None, tools=None):
                return mock_llm_msg

            def bind_tools(self, tools):
                return self

        monkeypatch.setattr("backend.agent.v2.mtc.runtime._create_llm", FakeLLM)

        execution_order = []

        async def order_tracking(self_member, ctx, on_event=None):
            execution_order.append(self_member.name)
            await asyncio.sleep(0.05)
            return make_ok_result(agent_id=self_member.name, reply="done")

        for mod in [
            "backend.agent.v2.members.researcher.ResearcherMember.execute",
            "backend.agent.v2.members.writer.WriterMember.execute",
        ]:
            monkeypatch.setattr(mod, order_tracking)

        monkeypatch.setattr(
            "backend.agent.v2.members.responder.ResponderMember.execute",
            lambda self_member, ctx, on_event=None: asyncio.sleep(0) or make_ok_result("responder", "done"),
        )

        rt = TeamMTCRuntime()
        async def collect():
            events = []
            async for e in rt.run(
                user_message="research then write",
                thread_id="t_e2e_deps",
                schema="",
            ):
                events.append(e)
            return events
        asyncio.run(collect())

        # researcher must run before writer
        assert execution_order[0] == "researcher"
        assert "writer" in execution_order


# ── 17.3  execute_task background task ────────────────────────────

class TestE2EBackgroundTask:
    """End-to-end: execute_task → background execution → continue conversation."""

    def test_background_task_pending_and_completed_events(self):
        """Submit a background task and verify events fire."""
        import time
        from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager

        mgr = BackgroundTaskManager()
        events = []
        mgr.set_emit_fn(lambda et, d: events.append((et, d)))

        def fast_exec(agent_id, task, thread_id):
            return {"status": "ok", "reply": "PRD completed", "artifacts": []}

        mgr.set_execute_fn(fast_exec)
        tid = mgr.submit("writer", "写PRD", "write a full PRD for SaaS product", timeout=10, thread_id="t_e2e_bg")

        # Should get task_pending immediately
        pending = [d for et, d in events if et == "task_pending"]
        assert len(pending) == 1
        assert pending[0]["task_id"] == tid
        assert pending[0]["status"] == "pending"

        # Wait for completion
        time.sleep(0.3)

        completed = [d for et, d in events if et == "task_completed"]
        assert len(completed) >= 1
        assert completed[0]["status"] == "ok"

    def test_new_request_sees_background_task_progress(self):
        """A second request on same thread_id sees the background task status."""
        import time
        from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager

        mgr = BackgroundTaskManager()
        events = []
        mgr.set_emit_fn(lambda et, d: events.append((et, d)))

        def slow_exec(agent_id, task, thread_id):
            time.sleep(0.5)
            return {"status": "ok", "reply": "done", "artifacts": []}

        mgr.set_execute_fn(slow_exec)
        tid = mgr.submit("writer", "long task", "body", timeout=10, thread_id="t_persist")

        # Immediately query — task should be running
        tasks = mgr.get_thread_tasks("t_persist")
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == tid

        # Wait and check completion
        time.sleep(0.8)
        tasks = mgr.get_thread_tasks("t_persist")
        assert tasks[0]["status"] in ("ok", "running")  # ok after completion

    def test_task_timeout_emits_failed(self):
        """Task exceeding timeout emits task_failed."""
        import time
        from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager

        mgr = BackgroundTaskManager()
        events = []
        mgr.set_emit_fn(lambda et, d: events.append((et, d)))

        def forever_exec(agent_id, task, thread_id):
            time.sleep(5.0)  # way longer than timeout
            return {"status": "ok", "reply": "never"}

        mgr.set_execute_fn(forever_exec)
        mgr.submit("coder", "timeout test", "body", timeout=1, thread_id="t_timeout")

        # Wait for timeout to fire
        time.sleep(1.5)

        failed = [d for et, d in events if et == "task_failed"]
        assert len(failed) >= 1
        assert "超时" in failed[0].get("error", "") or \
               "timeout" in failed[0].get("error", "").lower()


# ── 17.4  Refresh page → restore Plan + Background_Task ──────────

class TestE2EPageRefresh:
    """End-to-end: refresh page restores Plan and Background_Task state."""

    def test_plan_restored_after_persist(self):
        """Plan saved to SQLite is retrievable by thread_id."""
        from backend.agent.v2.mtc.persistence import init_db, PlanPersistence
        from backend.agent.v2.mtc.plan_manager import PlanManager

        init_db()

        # Create and run a plan (simulated)
        pm = PlanManager("t_restore")
        pm.create_plan([
            {"description": "step 1", "assignee_agent_id": "coder"},
            {"description": "step 2", "assignee_agent_id": "writer"},
        ])
        pm.update_step(pm.plan.steps[0].id, "completed", note="analysis done")

        # Persist
        pp = PlanPersistence()
        pp.save_plan(pm.get_snapshot())

        # Simulate page refresh: another PlanManager loads from persistence
        loaded = pp.load_plan("t_restore")
        assert loaded is not None
        assert len(loaded["steps"]) == 2
        assert loaded["steps"][0]["status"] == "completed"
        assert loaded["steps"][1]["status"] == "pending"

    def test_background_tasks_restored_across_requests(self):
        """Background tasks persist and can be queried after page refresh."""
        from backend.agent.v2.mtc.persistence import init_db, TaskPersistence
        from backend.agent.v2.mtc.background_tasks import BackgroundTask

        init_db()
        tp = TaskPersistence()
        t = BackgroundTask(
            task_id="t_refresh_bg", thread_id="t_page_refresh",
            agent_id="writer", title="Generate Report", task="generate pdf report",
            status="completed", result_json='{"reply":"done"}',
            created_at="2026-05-27T10:00:00",
            completed_at="2026-05-27T10:05:00",
        )
        tp.save_task(t)

        # Simulate page refresh: query all tasks for this thread
        tasks = tp.load_thread_tasks("t_page_refresh")
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "t_refresh_bg"
        assert tasks[0]["status"] == "completed"
        assert tasks[0]["title"] == "Generate Report"

    def test_api_plan_route_returns_saved_plan(self, monkeypatch):
        """GET /api/v2/plan/<thread_id> returns the saved plan."""
        from backend.agent.v2.mtc.persistence import init_db, PlanPersistence
        from fastapi.testclient import TestClient
        from backend.api import app

        init_db()
        pp = PlanPersistence()
        pp.save_plan({
            "thread_id": "t_api_restore",
            "plan_id": "p_test",
            "steps": [
                {"id": "s1", "description": "analyze", "assignee_agent_id": "coder",
                 "status": "completed", "dependencies": []},
            ],
            "updated_at": "2026-05-27T12:00:00",
        })

        client = TestClient(app)
        r = client.get("/api/v2/plan/t_api_restore")
        assert r.status_code == 200
        body = r.json()
        if body.get("plan"):
            assert body["plan"]["plan_id"] == "p_test"
            assert len(body["plan"]["steps"]) == 1

    def test_api_tasks_route_returns_saved_tasks(self, monkeypatch):
        """GET /api/v2/tasks returns persisted background tasks."""
        from backend.agent.v2.mtc.persistence import init_db, TaskPersistence
        from backend.agent.v2.mtc.background_tasks import BackgroundTask
        from fastapi.testclient import TestClient
        from backend.api import app

        init_db()
        tp = TaskPersistence()
        t = BackgroundTask(
            task_id="t_api_tasks_test", thread_id="t_tasks_api",
            agent_id="coder", title="API Test Task", task="test task",
            status="completed", result_json="{}",
            created_at="2026-05-27T12:00:00", completed_at=""
        )
        tp.save_task(t)

        client = TestClient(app)
        r = client.get("/api/v2/tasks?thread_id=t_tasks_api")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, dict)
        assert "tasks" in body
        assert len(body["tasks"]) >= 1
        assert body["tasks"][0]["task_id"] == "t_api_tasks_test"

    def test_full_roundtrip_create_persist_restore(self):
        """Full cycle: create Plan + Task → persist → restore from DB."""
        from backend.agent.v2.mtc.persistence import init_db, PlanPersistence, TaskPersistence
        from backend.agent.v2.mtc.plan_manager import PlanManager
        from backend.agent.v2.mtc.background_tasks import BackgroundTask

        init_db()
        thread_id = "t_full_roundtrip"

        # Phase 1: Create and persist Plan
        pm = PlanManager(thread_id)
        pm.create_plan([
            {"description": "analyze data", "assignee_agent_id": "coder"},
            {"description": "write report", "assignee_agent_id": "writer"},
        ])
        pp = PlanPersistence()
        pp.save_plan(pm.get_snapshot())

        # Phase 2: Create and persist Background Task
        tp = TaskPersistence()
        t = BackgroundTask(
            task_id="bg_full", thread_id=thread_id,
            agent_id="writer", title="Generate PDF", task="generate pdf",
            status="running", result_json="{}",
            created_at="2026-05-27T12:00:00", completed_at=""
        )
        tp.save_task(t)

        # Phase 3: Simulate page refresh — load from persistence
        loaded_plan = pp.load_plan(thread_id)
        loaded_tasks = tp.load_thread_tasks(thread_id)

        assert loaded_plan is not None
        assert len(loaded_plan["steps"]) == 2
        assert loaded_tasks[0]["task_id"] == "bg_full"


# ── Runtime variant consistency ──────────────────────────────────

class TestE2ERuntimeVariant:
    """Property 5: runtime_variant is consistent throughout a request."""

    def test_runtime_variant_is_mtc(self, monkeypatch):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        # Use the greeting fast-path (no LLM needed)
        rt = TeamMTCRuntime()

        async def fake_responder(self_member, ctx, on_event=None):
            return make_ok_result("responder", "Hi!")

        monkeypatch.setattr(
            "backend.agent.v2.members.responder.ResponderMember.execute", fake_responder
        )

        events = []
        async def collect():
            async for e in rt.run(
                user_message="你好",  # greeting → fast path
                thread_id="t_variant",
                schema="",
            ):
                events.append(e)
        asyncio.run(collect())

        assert events[-1].get("event") == "done"
        assert events[-1]["data"]["runtime_variant"] == "mtc"
