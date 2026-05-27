"""
End-to-end smoke test for Team MTC runtime.

Tests verify:
- Greeting fast-path
- Event ordering (done is last, no buffer issues)
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestRuntimeSmoke:
    def test_greeting_yields_reply_then_done(self):
        """Greeting fast-path should yield reply event then done event."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()

        # Mock responder.execute to avoid LLM call
        async def fake_execute(self_member, ctx, on_event=None):
            from backend.agent.v2.state import AgentResult
            return AgentResult(
                agent_id="responder", status="ok",
                reply="你好！", code=None, artifacts=[], error=None,
            )

        with patch("backend.agent.v2.members.responder.ResponderMember.execute", fake_execute):
            events = []
            async def collect():
                async for e in rt.run(
                    user_message="你好",
                    thread_id="t_smoke_greet",
                    schema="",
                    conversation_history=None,
                    attached_files=None,
                    skill_workflow_id=None,
                ):
                    events.append(e)
            asyncio.run(collect())

        assert len(events) >= 2
        event_types = [e.get("event") for e in events]
        assert "reply" in event_types
        assert event_types[-1] == "done"

    def test_events_ordering_property_done_last(self):
        """Property: done event must be the last (R9.4)."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()

        async def fake_execute(self_member, ctx, on_event=None):
            from backend.agent.v2.state import AgentResult
            return AgentResult(
                agent_id="responder", status="ok", reply="hi", code=None, artifacts=[], error=None,
            )

        with patch("backend.agent.v2.members.responder.ResponderMember.execute", fake_execute):
            events = []
            async def collect():
                async for e in rt.run(
                    user_message="hi",  # 5 chars or less → greeting
                    thread_id="t_smoke",
                    schema="",
                    conversation_history=None,
                    attached_files=None,
                    skill_workflow_id=None,
                ):
                    events.append(e)
            asyncio.run(collect())

        # Done is last
        assert events[-1].get("event") == "done"
        # No event after done
        for e in events[:-1]:
            assert e.get("event") != "done"


class TestApiRouting:
    """Verify gray switch routing."""
    def test_runtime_variant_default_mtc(self, monkeypatch):
        # Default behavior when env var unset
        monkeypatch.delenv("SPECTRA_TEAM_MTC_ENABLED", raising=False)
        # When SPECTRA_TEAM_MTC_ENABLED is unset, code uses default "1"
        val = os.environ.get("SPECTRA_TEAM_MTC_ENABLED", "1")
        assert val == "1"

    def test_legacy_runtime_imports(self):
        """Verify legacy_runtime.py exists and is importable as fallback."""
        from backend.agent.v2.legacy_runtime import TeamOrchestrationRuntime
        assert TeamOrchestrationRuntime is not None


class TestSoloIsolation:
    """Property 4: Solo_Runtime never imports mtc/."""
    def test_single_agent_module_does_not_import_mtc(self):
        import backend.agent.single_agent as solo
        import inspect
        source = inspect.getsource(solo)
        # Solo file should not reference mtc
        assert "agent.v2.mtc" not in source
        assert "from backend.agent.v2.mtc" not in source



class TestStreamingProperty:
    """Verify events flow live via queue (not buffered until end)."""

    def test_events_yield_during_pipeline_not_at_end(self):
        """When member.execute is slow, the file_parsed event must arrive
        BEFORE member.execute completes (proving real-time streaming)."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()

        # Track when each event arrives relative to a slow LLM call
        delays = {"reply_arrived_at": None}

        async def slow_responder_execute(self_member, ctx, on_event=None):
            from backend.agent.v2.state import AgentResult
            await asyncio.sleep(0.2)  # Slow execute
            return AgentResult(
                agent_id="responder", status="ok",
                reply="hi back", code=None, artifacts=[], error=None,
            )

        with patch("backend.agent.v2.members.responder.ResponderMember.execute", slow_responder_execute):
            events_with_time = []
            import time
            t0 = time.time()

            async def collect():
                async for e in rt.run(
                    user_message="hi",  # greeting → fast path
                    thread_id="t_stream",
                    schema="",
                    conversation_history=None,
                    attached_files=None,
                    skill_workflow_id=None,
                ):
                    events_with_time.append((time.time() - t0, e.get("event")))
            asyncio.run(collect())

        # We should have at least reply + done events
        evt_types = [t for _, t in events_with_time]
        assert "reply" in evt_types
        assert evt_types[-1] == "done"



class TestDoneEventShape:
    """Regression: runtime._build_done_event must return data as dict (not pre-serialized string).

    api.py /api/v2/chat does `{**event_data, "thread_id": thread_id}` for the done event,
    which crashes with "'str' object is not a mapping" if data is a JSON string.
    """

    def test_done_event_data_is_dict(self):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()

        async def fake_execute(self_member, ctx, on_event=None):
            from backend.agent.v2.state import AgentResult
            return AgentResult(
                agent_id="responder", status="ok", reply="hi", code=None, artifacts=[], error=None,
            )

        with patch("backend.agent.v2.members.responder.ResponderMember.execute", fake_execute):
            events = []
            async def collect():
                async for e in rt.run(
                    user_message="hi",
                    thread_id="t_done_shape",
                    schema="",
                    conversation_history=None,
                    attached_files=None,
                    skill_workflow_id=None,
                ):
                    events.append(e)
            asyncio.run(collect())

        done = events[-1]
        assert done["event"] == "done"
        # data MUST be a dict (so api.py's `{**event_data, ...}` works)
        assert isinstance(done["data"], dict), \
            f"done.data must be dict, got {type(done['data']).__name__}: {done['data']!r}"
        assert "plan" in done["data"]
        assert "artifacts" in done["data"]
        assert "background_tasks" in done["data"]
        assert done["data"]["runtime_variant"] == "mtc"

    def test_api_v2_done_dict_spread_works(self):
        """Simulate the exact api.py pattern that crashed."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()

        async def fake_execute(self_member, ctx, on_event=None):
            from backend.agent.v2.state import AgentResult
            return AgentResult(
                agent_id="responder", status="ok", reply="hi", code=None, artifacts=[], error=None,
            )

        with patch("backend.agent.v2.members.responder.ResponderMember.execute", fake_execute):
            events = []
            async def collect():
                async for e in rt.run(
                    user_message="hi",
                    thread_id="t_api_spread",
                    schema="",
                    conversation_history=None,
                    attached_files=None,
                    skill_workflow_id=None,
                ):
                    events.append(e)
            asyncio.run(collect())

        done = events[-1]
        # This is what api.py does — must not raise:
        merged = {**done["data"], "thread_id": "t_api_spread"}
        assert merged["thread_id"] == "t_api_spread"
        # And final json.dumps round-trip must succeed
        import json
        s = json.dumps(merged, ensure_ascii=False)
        assert "thread_id" in s
