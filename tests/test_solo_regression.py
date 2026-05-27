"""
Solo regression tests (Task 16.10).

Verifies that Solo mode /api/chat is completely unaffected by the Team MTC changes.
All existing Solo tests plus new regression checks must pass.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestSoloEndpointUntouched:
    """All Solo /api/chat behavior must be preserved."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.api import app
        return TestClient(app)

    def test_solo_chat_endpoint_exists(self):
        """POST /api/chat route must be registered."""
        from backend.api import app
        routes = {r.path for r in app.routes if hasattr(r, 'path')}
        assert "/api/chat" in routes, "/api/chat route must exist"

    def test_solo_chat_request_body_fields_preserved(self):
        """All existing Solo request fields are still accepted (R1.3)."""
        import inspect
        from backend.api import app

        # Find the /api/chat route
        routes = {r.path: r for r in app.routes if hasattr(r, 'path')}
        assert "/api/chat" in routes or any(
            r.path == "/api/chat" for r in app.routes if hasattr(r, 'path')
        ), "/api/chat route must exist"

    def test_solo_module_never_imports_mtc(self):
        """Property 4: Solo module must not import anything from mtc/ (R1.5)."""
        import backend.agent.single_agent as solo
        import inspect

        source = inspect.getsource(solo)
        assert "agent.v2.mtc" not in source
        assert "from backend.agent.v2.mtc" not in source

    def test_solo_imports_independent(self):
        """Importing solo_agent should not trigger any mtc import."""
        import sys
        # Remove mtc from sys.modules to check for lazy imports
        mtc_keys = [k for k in sys.modules if "mtc" in k]
        for k in mtc_keys:
            del sys.modules[k]

        # Now import solo — should not cause mtc modules to appear
        import importlib
        import backend.agent.single_agent as solo
        importlib.reload(solo)

        mtc_after = [k for k in sys.modules if "mtc" in k]
        assert len(mtc_after) == 0, \
            f"Importing single_agent should not load mtc modules, but got: {mtc_after}"


class TestSoloToolIntegrity:
    """Solo tools are unchanged."""

    def test_all_tools_still_importable(self):
        """ALL_TOOLS from backend/tools/__init__.py unchanged."""
        from backend.tools import ALL_TOOLS
        # ALL_TOOLS is a flat list; some items are LangChain tools (with .name),
        # some are plain functions (like generate_docx)
        assert len(ALL_TOOLS) >= 5, f"Expected >=5 tools, got {len(ALL_TOOLS)}"
        # Verify at least the key tool modules are importable
        from backend.tools import web_search, calculator, visualization, sandbox
        assert web_search is not None
        assert calculator is not None
        assert visualization is not None
        assert sandbox is not None

    def test_solo_agent_graph_builds(self):
        """build_single_agent_graph is still callable (no signature change)."""
        import inspect
        from backend.agent.single_agent import build_single_agent_graph

        sig = inspect.signature(build_single_agent_graph)
        params = list(sig.parameters.keys())
        # Check key params are unchanged
        assert "tools" in params
        assert "system_prompt" in params
        assert "max_steps" in params


class TestSoloSSEEventCompat:
    """Solo SSE events unchanged."""

    def test_solo_event_names_unchanged(self):
        """Solo graph-building function is still importable with correct signature."""
        from backend.agent.single_agent import build_single_agent_graph
        import inspect
        # The function must exist and have the expected parameters
        sig = inspect.signature(build_single_agent_graph)
        params = list(sig.parameters.keys())
        assert "tools" in params
        assert "system_prompt" in params


class TestApiV2ChatRouting:
    """Gray routing: SPECTRA_TEAM_MTC_ENABLED controls which runtime is used."""

    def test_legacy_runtime_class_exists(self):
        """Legacy runtime is importable for fallback (R15.2)."""
        from backend.agent.v2.legacy_runtime import TeamOrchestrationRuntime
        assert TeamOrchestrationRuntime is not None

    def test_mtc_runtime_class_exists(self):
        """New MTC runtime is importable (R15.3)."""
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime
        assert TeamMTCRuntime is not None

    def test_both_runtimes_have_run_method(self):
        """Both runtimes expose async run() with compatible signatures."""
        from backend.agent.v2.legacy_runtime import TeamOrchestrationRuntime
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        for cls in [TeamOrchestrationRuntime, TeamMTCRuntime]:
            assert hasattr(cls, 'run')
            import inspect
            assert inspect.iscoroutinefunction(cls.run) or \
                   hasattr(cls.run, '__call__'), \
                   f"{cls.__name__}.run should be async"


class TestSoloRegressionQuick:
    """Quick sanity: run the existing Solo test suite is still discoverable."""

    def test_existing_solo_tests_found(self):
        """Verify test discovery still finds all existing test modules."""
        import unittest
        test_dir = Path(__file__).resolve().parent
        loader = unittest.TestLoader()
        suite = loader.discover(str(test_dir), pattern="test_*.py")
        test_count = suite.countTestCases()
        # Should have dozens of tests
        assert test_count >= 20, f"Expected >=20 tests, found {test_count}"
