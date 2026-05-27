"""
Regression tests for coder/validator quality improvements.

Background: User reported "cleaned_*.xlsx 只有表头没有数据"，原因是：
1. coder 默认走 'analyzer' validator，最宽松，没产物只有 stdout 也算"通过"
2. validator 没检查 cleaned xlsx 的行数
3. plan/coder prompt 没显式约束目标表名，LLM 误把 search_results 等当成清洗目标

修复:
1. CoderMember._validator_sender_alias() 根据 instruction 关键词动态映射
2. _validate_execution 对 cleaner 任务额外读取 xlsx 校验行数 > 0
3. coder/plan prompt 显式列出目标表名 + 禁止其它表
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestCoderSenderAliasDetection:
    """Coder dynamic validator alias selection based on task keywords."""

    def _make_coder(self, instruction: str, task_goal: str = ""):
        from backend.agent.v2.members.coder import CoderMember
        from backend.agent.v2.members.base import MemberContext
        member = CoderMember()
        ctx = MemberContext(instruction=instruction, task_goal=task_goal, thread_id="t")
        # Simulate execute() context capture
        member._active_ctx = ctx
        return member

    def test_clean_keyword_routes_to_cleaner(self):
        for kw in ["清洗这张表", "去重", "处理缺失值", "整理数据"]:
            member = self._make_coder(kw)
            assert member._validator_sender_alias() == "cleaner", \
                f"keyword {kw!r} should route to cleaner"

    def test_chart_keyword_routes_to_visualizer(self):
        for kw in ["生成可视化图表", "画一个对比图", "趋势分布"]:
            member = self._make_coder(kw)
            assert member._validator_sender_alias() == "visualizer"

    def test_predict_keyword_routes_to_predictor(self):
        for kw in ["预测下个月销量", "训练回归模型", "聚类分析"]:
            member = self._make_coder(kw)
            assert member._validator_sender_alias() == "predictor"

    def test_no_keyword_falls_back_to_analyzer(self):
        member = self._make_coder("看一下数据有什么特征")
        assert member._validator_sender_alias() == "analyzer"

    def test_cleaner_takes_priority_over_visualizer(self):
        """When task asks for cleaning AND visualization, cleaner wins (more strict)."""
        member = self._make_coder("先清洗再画对比图")
        assert member._validator_sender_alias() == "cleaner"


class TestEmptyCleanedXlsxFails:
    """Validator must reject cleaned xlsx that contains only header (0 data rows)."""

    def _make_xlsx(self, with_rows: bool) -> Path:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["col_a", "col_b", "col_c"])
        if with_rows:
            ws.append([1, 2, 3])
            ws.append([4, 5, 6])
        out_dir = Path(tempfile.mkdtemp())
        out = out_dir / "cleaned_xyz.xlsx"
        wb.save(out)
        wb.close()
        return out

    def test_zero_row_xlsx_marked_as_failed(self):
        from backend.agent.v2.infra.executor_impl import _validate_execution
        from backend.app_paths import ARTIFACTS_DIR

        xlsx = self._make_xlsx(with_rows=False)
        # cleaned_file_path 在生产里是相对 ARTIFACTS_DIR 的路径，文件名级别
        target = ARTIFACTS_DIR / "cleaned_test_empty.xlsx"
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(xlsx.read_bytes())

        try:
            state = {
                "sender": "cleaner",
                "cleaned_file_path": "cleaned_test_empty.xlsx",
                "execution_result": "处理完成",
                "last_traceback": "",
                "last_stderr": "",
                "artifacts": [{"type": "cleaned_data", "path": "cleaned_test_empty.xlsx"}],
            }
            result = _validate_execution(state)
            assert result["ok"] is False, "empty xlsx must NOT pass validation"
            assert "零行数据" in result["diagnostic"] or "只有表头" in result["diagnostic"]
        finally:
            target.unlink(missing_ok=True)

    def test_nonempty_xlsx_passes(self):
        from backend.agent.v2.infra.executor_impl import _validate_execution
        from backend.app_paths import ARTIFACTS_DIR

        xlsx = self._make_xlsx(with_rows=True)
        target = ARTIFACTS_DIR / "cleaned_test_with_rows.xlsx"
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        target.write_bytes(xlsx.read_bytes())

        try:
            state = {
                "sender": "cleaner",
                "cleaned_file_path": "cleaned_test_with_rows.xlsx",
                "execution_result": "已写出 2 行清洗结果",
                "last_traceback": "",
                "last_stderr": "",
                "artifacts": [{"type": "cleaned_data", "path": "cleaned_test_with_rows.xlsx"}],
            }
            result = _validate_execution(state)
            assert result["ok"] is True, f"non-empty xlsx must pass; diagnostic={result['diagnostic']}"
        finally:
            target.unlink(missing_ok=True)


class TestCoderPromptIncludesTargetTable:
    """Coder prompt must list the target table name and forbid other tables."""

    def test_target_tables_block_present(self):
        from backend.agent.v2.prompts.coder import build_coder_prompt
        prompt = build_coder_prompt(
            instruction="清洗",
            schema="some-schema",
            target_tables=["非常脏的用户表"],
        )
        assert "非常脏的用户表" in prompt
        # 强约束：禁止 search_results / daily_news 等其它表
        assert "search_results" in prompt
        assert "禁止" in prompt or "不要" in prompt

    def test_no_target_table_emits_no_block(self):
        from backend.agent.v2.prompts.coder import build_coder_prompt
        prompt = build_coder_prompt(instruction="只看一下", target_tables=None)
        assert "必须操作的目标表" not in prompt


class TestPlanPromptIncludesTargetTable:
    """Plan-level prompt must instruct the LLM to embed target table in step descriptions."""

    def test_plan_prompt_lists_attached_tables(self):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()
        rt._attached_files = [{"table_name": "非常脏的用户表", "name": "users.xlsx"}]
        prompt = rt._build_plan_system_prompt(
            schema="",
            parsed_texts="",
            template_steps=None,
            skill_workflow_id=None,
        )
        assert "非常脏的用户表" in prompt
        assert "目标表" in prompt or "数据来源约束" in prompt

    def test_plan_prompt_no_attached_no_constraint(self):
        from backend.agent.v2.mtc.runtime import TeamMTCRuntime

        rt = TeamMTCRuntime()
        rt._attached_files = []
        prompt = rt._build_plan_system_prompt(
            schema="",
            parsed_texts="",
            template_steps=None,
            skill_workflow_id=None,
        )
        assert "数据来源约束" not in prompt
