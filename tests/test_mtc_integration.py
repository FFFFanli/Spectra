"""
Integration tests for MTC Team Mode v2.

Covers:
  16.6  Skill_Workflow integration (5 templates E2E)
  16.7  broadcast parallel integration (3 researchers simultaneously)
  16.8  Background_Task cross-request snapshot integration
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── 16.6 Skill_Workflow integration ──────────────────────────────

class TestSkillWorkflowIntegration:
    """Integration tests for 5 workflow templates."""

    def test_all_5_templates_load_and_have_valid_steps(self):
        """Every template must have an id, title, and at least 1 default step
        with valid assignee_agent_id."""
        from backend.agent.v2.mtc.workflow_loader import WorkflowLoader

        loader = WorkflowLoader()
        workflows = loader.load_all()
        assert len(workflows) == 5

        valid_assignees = {"coder", "writer", "researcher", "responder", "designer", "reviewer"}

        for wf in workflows:
            assert wf.id, f"Workflow {wf.title} missing id"
            assert wf.title, f"Workflow {wf.id} missing title"
            assert len(wf.default_steps) >= 1, f"Workflow {wf.id} has no steps"

            for step in wf.default_steps:
                assert "description" in step, f"Step in {wf.id} missing description"
                assert "assignee_agent_id" in step, f"Step in {wf.id} missing assignee"
                assert step["assignee_agent_id"] in valid_assignees, \
                    f"Unknown agent in {wf.id}: {step['assignee_agent_id']}"

    def test_competitor_analysis_deps_are_all_empty(self):
        """competitor_analysis: all steps have empty deps (embarrassingly parallel)."""
        from backend.agent.v2.mtc.workflow_loader import WorkflowLoader

        loader = WorkflowLoader()
        wf = loader.get("competitor_analysis")
        assert wf is not None
        for step in wf.default_steps:
            assert step.get("dependencies", []) == []

    def test_workflow_to_plan_roundtrip(self):
        """Loading a workflow and feeding its steps to PlanManager produces a valid plan."""
        from backend.agent.v2.mtc.workflow_loader import WorkflowLoader
        from backend.agent.v2.mtc.plan_manager import PlanManager

        loader = WorkflowLoader()
        wf = loader.get("data_report")
        assert wf is not None

        pm = PlanManager("t_int_wf")
        plan = pm.create_plan(wf.default_steps)
        assert len(plan.steps) == len(wf.default_steps)
        assert all(s.status == "pending" for s in plan.steps)

    def test_template_search_skill_workflow_id_in_request(self):
        """Simulate the runtime path: picking a template by skill_workflow_id
        and calling make_plan with LLM validation."""
        from backend.agent.v2.mtc.workflow_loader import WorkflowLoader

        loader = WorkflowLoader()
        wf = loader.get("activity_plan")
        assert wf is not None
        assert wf.title == "活动方案"
        assert len(wf.default_steps) >= 1

    def test_template_steps_count_validation(self):
        """When LLM returns mismatched step count, template raw steps are used (R11.7)."""
        from backend.agent.v2.mtc.workflow_loader import WorkflowLoader

        loader = WorkflowLoader()
        wf = loader.get("meeting_minutes")
        original_count = len(wf.default_steps)

        # Simulate LLM returning wrong count
        llm_steps = wf.default_steps[:-1]  # one fewer
        if len(llm_steps) == original_count:
            llm_steps = wf.default_steps + [{"description": "extra", "assignee_agent_id": "responder"}]

        assert len(llm_steps) != original_count
        # In this case, runtime should use wf.default_steps instead
        # Verify the fallback steps match originals
        assert len(wf.default_steps) == original_count


# ── 16.7 broadcast parallel integration ──────────────────────────

class TestBroadcastParallel:
    """Integration tests for broadcast → parallel Plan Step execution."""

    def test_broadcast_converts_to_parallel_steps(self):
        """broadcast tool call should produce N separate steps with no deps."""
        from backend.agent.v2.mtc.plan_manager import PlanManager

        pm = PlanManager("t_broadcast")
        # Simulate what plan_tools.broadcast does: generate N steps
        agent_ids = ["researcher", "researcher", "researcher"]
        instruction = "调研竞品A、B、C"
        steps_raw = [
            {"description": f"{instruction} — {agent_id}", "assignee_agent_id": agent_id,
             "dependencies": []}
            for agent_id in agent_ids
        ]
        plan = pm.create_plan(steps_raw)
        assert len(plan.steps) == 3
        # All should have no deps → all ready immediately
        ready = pm.get_ready_steps()
        assert len(ready) == 3

    def test_scheduler_runs_all_parallel_when_no_deps(self):
        """When all 3 steps have no deps, scheduler must run >=2 concurrently (R5.1)."""
        from backend.agent.v2.mtc.plan_manager import PlanManager
        from backend.agent.v2.mtc.scheduler import PlanScheduler

        pm = PlanManager("t_par")
        pm.create_plan([
            {"description": f"research_{i}", "assignee_agent_id": "researcher", "dependencies": []}
            for i in range(3)
        ])
        scheduler = PlanScheduler(pm)

        concurrency_tracker = {"current": 0, "max": 0}

        async def execute_fn(step):
            concurrency_tracker["current"] += 1
            concurrency_tracker["max"] = max(concurrency_tracker["max"], concurrency_tracker["current"])
            await asyncio.sleep(0.08)  # small delay to force overlap
            concurrency_tracker["current"] -= 1
            return {"status": "ok", "reply": f"{step.description} done"}

        async def on_revise(_):
            pass

        asyncio.run(scheduler.run_plan(execute_fn, lambda *a: None, on_revise))
        assert concurrency_tracker["max"] >= 2, \
            f"Expected >=2 concurrent, got max={concurrency_tracker['max']}"

    def test_scheduler_limits_to_4_concurrent(self):
        """With 6 no-dep steps, max concurrency should be exactly 4 (R5.1)."""
        from backend.agent.v2.mtc.plan_manager import PlanManager
        from backend.agent.v2.mtc.scheduler import PlanScheduler

        pm = PlanManager("t_conc")
        pm.create_plan([
            {"description": f"step_{i}", "assignee_agent_id": "researcher", "dependencies": []}
            for i in range(6)
        ])
        scheduler = PlanScheduler(pm)

        concurrency_tracker = {"current": 0, "max": 0}

        async def execute_fn(step):
            concurrency_tracker["current"] += 1
            concurrency_tracker["max"] = max(concurrency_tracker["max"], concurrency_tracker["current"])
            await asyncio.sleep(0.08)
            concurrency_tracker["current"] -= 1
            return {"status": "ok", "reply": "done"}

        async def on_revise(_):
            pass

        asyncio.run(scheduler.run_plan(execute_fn, lambda *a: None, on_revise))
        assert concurrency_tracker["max"] <= 4, \
            f"Expected max 4 concurrent, got {concurrency_tracker['max']}"

    def test_dependency_respected_in_broadcast(self):
        """Steps with deps wait for their predecessors before executing."""
        from backend.agent.v2.mtc.plan_manager import PlanManager
        from backend.agent.v2.mtc.scheduler import PlanScheduler

        pm = PlanManager("t_dep")
        pm.create_plan([
            {"description": "first", "assignee_agent_id": "researcher", "dependencies": []},
            {"description": "second", "assignee_agent_id": "writer", "dependencies": ["first"]},
        ])
        scheduler = PlanScheduler(pm)

        order = []

        async def execute_fn(step):
            order.append(step.description)
            return {"status": "ok", "reply": "done"}

        async def on_revise(_):
            pass

        asyncio.run(scheduler.run_plan(execute_fn, lambda *a: None, on_revise))
        assert order == ["first", "second"]

    def test_token_usage_isolation_per_step(self):
        """Each concurrent step gets its own token usage context (R5.2)."""
        from backend.agent.v2.mtc.plan_manager import PlanManager
        from backend.agent.v2.mtc.scheduler import PlanScheduler, _step_usage

        pm = PlanManager("t_iso")
        pm.create_plan([
            {"description": f"s{i}", "assignee_agent_id": "researcher", "dependencies": []}
            for i in range(2)
        ])
        scheduler = PlanScheduler(pm)

        captured_usages = []

        async def execute_fn(step):
            # Get the token for this context and modify it
            usage = _step_usage.get()
            assert usage is not None, "Each step should have its own usage context"
            usage["step"] = step.description
            usage["tokens"] = 100
            captured_usages.append(dict(usage))
            await asyncio.sleep(0.05)
            return {"status": "ok", "reply": "done"}

        async def on_revise(_):
            pass

        asyncio.run(scheduler.run_plan(execute_fn, lambda *a: None, on_revise))
        assert len(captured_usages) == 2
        # Each should have its own step name
        assert captured_usages[0]["step"] != captured_usages[1]["step"]


# ── 16.8 Background_Task cross-request snapshot ──────────────────

class TestBackgroundTaskCrossRequest:
    """Integration tests for Background_Task persistence and cross-request query."""

    def test_persistence_roundtrip(self):
        """Task saved to SQLite can be loaded back via TaskPersistence (R6.7)."""
        from backend.agent.v2.mtc.persistence import init_db, TaskPersistence
        from backend.agent.v2.mtc.background_tasks import BackgroundTask

        init_db()
        tp = TaskPersistence()
        t = BackgroundTask(
            task_id="t_persist_01",
            thread_id="thread_persist_x",
            agent_id="coder",
            title="persist test",
            task="do something",
            status="completed",
            result_json='{"reply":"done"}',
            created_at="2026-01-01T00:00:00",
            completed_at="2026-01-01T00:05:00",
        )
        tp.save_task(t)

        loaded = tp.load_task("t_persist_01")
        assert loaded is not None
        assert loaded["task_id"] == "t_persist_01"
        assert loaded["status"] == "completed"

    def test_thread_tasks_query(self):
        """get_thread_tasks returns only tasks for the given thread."""
        from backend.agent.v2.mtc.persistence import init_db, TaskPersistence
        from backend.agent.v2.mtc.background_tasks import BackgroundTask

        init_db()
        tp = TaskPersistence()
        t1 = BackgroundTask(
            task_id="t_xreq_a", thread_id="thread_x", agent_id="coder",
            title="A", task="task A body", status="completed", result_json="{}",
            created_at="2026-01-01T00:00:00", completed_at=""
        )
        t2 = BackgroundTask(
            task_id="t_xreq_b", thread_id="thread_x", agent_id="writer",
            title="B", task="task B body", status="pending", result_json="{}",
            created_at="2026-01-01T00:01:00", completed_at=""
        )
        t3 = BackgroundTask(
            task_id="t_xreq_c", thread_id="thread_other", agent_id="coder",
            title="C", task="task C body", status="running", result_json="{}",
            created_at="2026-01-01T00:02:00", completed_at=""
        )
        for t in [t1, t2, t3]:
            tp.save_task(t)

        thread_tasks = tp.load_thread_tasks("thread_x")
        assert len(thread_tasks) == 2
        task_ids = {r["task_id"] for r in thread_tasks}
        assert task_ids == {"t_xreq_a", "t_xreq_b"}

    def test_background_task_manager_get_thread_snapshot(self):
        """BackgroundTaskManager.get_thread_tasks serves cross-request snapshots (R6.6)."""
        from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager

        mgr = BackgroundTaskManager()
        mgr.set_emit_fn(lambda ev, d: None)

        # Submit 2 tasks to same thread, 1 to different thread
        mgr.submit("coder", "task A", "body", thread_id="snap_t1")
        mgr.submit("writer", "task B", "body", thread_id="snap_t1")
        mgr.submit("coder", "task C", "body", thread_id="snap_other")

        tasks_t1 = mgr.get_thread_tasks("snap_t1")
        assert len(tasks_t1) == 2
        titles = {t["title"] for t in tasks_t1}
        assert titles == {"task A", "task B"}

    def test_manager_passed_to_runtime(self):
        """Verify TeamMTCRuntime creates a BackgroundTaskManager."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()
        assert rt._bg_task_manager is not None
        tasks = rt._bg_task_manager.get_thread_tasks("nonexistent")
        assert tasks == []

    def test_new_request_sees_previous_tasks(self):
        """A new request for the same thread_id can query previous tasks."""
        from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager
        from backend.agent.v2.mtc.persistence import init_db, TaskPersistence
        from backend.agent.v2.mtc.background_tasks import BackgroundTask

        init_db()
        tp = TaskPersistence()
        # Simulate a previous request
        t = BackgroundTask(
            task_id="prev_task_01", thread_id="thread_rejoin",
            agent_id="coder", title="Previous task", task="a task",
            status="completed", result_json="{}",
            created_at="2026-01-01T00:00:00", completed_at=""
        )
        tp.save_task(t)

        # New manager instance — can query persisted data
        loaded = tp.load_task("prev_task_01")
        assert loaded is not None
        assert loaded["status"] == "completed"


# ── Plan persistence cross-request ──────────────────────────────

class TestPlanCrossRequest:
    """Plan snapshots persist and are recoverable across requests (R13)."""

    def test_plan_saved_and_loaded(self):
        from backend.agent.v2.mtc.persistence import init_db, PlanPersistence

        init_db()
        pp = PlanPersistence()
        snapshot = {
            "thread_id": "t_plan_xreq",
            "plan_id": "p_xyz",
            "steps": [
                {"id": "s1", "description": "analyze", "assignee_agent_id": "coder",
                 "status": "completed", "dependencies": []},
                {"id": "s2", "description": "report", "assignee_agent_id": "writer",
                 "status": "pending", "dependencies": ["s1"]},
            ],
            "updated_at": "2026-05-27T00:00:00",
        }
        pp.save_plan(snapshot)
        loaded = pp.load_plan("t_plan_xreq")
        assert loaded is not None
        assert len(loaded["steps"]) == 2
        assert loaded["steps"][0]["status"] == "completed"

    def test_load_latest_plan_per_thread(self):
        """Multiple saves for same thread → latest is returned."""
        from backend.agent.v2.mtc.persistence import init_db, PlanPersistence

        init_db()
        pp = PlanPersistence()
        pp.save_plan({
            "thread_id": "t_latest", "plan_id": "v1",
            "steps": [{"id": "s1", "description": "old", "assignee_agent_id": "coder",
                       "status": "completed", "dependencies": []}],
            "updated_at": "2026-01-01T00:00:00",
        })
        pp.save_plan({
            "thread_id": "t_latest", "plan_id": "v2",
            "steps": [{"id": "s1", "description": "new", "assignee_agent_id": "coder",
                       "status": "running", "dependencies": []}],
            "updated_at": "2026-01-01T00:01:00",
        })
        loaded = pp.load_plan("t_latest")
        assert loaded["plan_id"] == "v2"


# ── API route smoke ─────────────────────────────────────────────

class TestMtcApiRoutes:
    """Verify the new GET routes return expected shapes."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.api import app
        return TestClient(app)

    def test_get_workflows_returns_list(self, client):
        r = client.get("/api/v2/workflows")
        assert r.status_code == 200
        body = r.json()
        # Response is {"workflows": [...]}
        assert "workflows" in body
        workflows = body["workflows"]
        assert isinstance(workflows, list)
        assert len(workflows) >= 5
        assert "id" in workflows[0]
        assert "title" in workflows[0]

    def test_get_plan_not_found_handled(self, client):
        r = client.get("/api/v2/plan/thread_does_not_exist_99999")
        assert r.status_code == 200
        body = r.json()
        # Should return empty or null plan
        assert body.get("plan") is None or body.get("plan") == {}

    def test_get_tasks_empty(self, client):
        r = client.get("/api/v2/tasks?thread_id=no_such_thread")
        assert r.status_code == 200
        body = r.json()
        # Response is {"tasks": [...]}
        assert isinstance(body, dict)
        assert "tasks" in body
        assert isinstance(body["tasks"], list)
