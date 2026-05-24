"""
测试定时任务工具：创建、列表、暂停、删除。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class CronManagerDbTests(unittest.TestCase):
    """测试 cron_jobs 的数据库操作。"""

    @classmethod
    def setUpClass(cls):
        # 使用临时数据库
        import tempfile
        os.environ["STATE_DB_PATH"] = os.path.join(
            tempfile.gettempdir(), "test_spectra_cron.db"
        )
        from backend.app_paths import DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        from backend.state_store import init_state_store
        init_state_store()

    # ── 数据库 CRUD ──

    def test_save_and_list_cron_job(self):
        from backend.state_store import save_cron_job, list_cron_jobs, delete_cron_job
        save_cron_job("cj-1", "0 9 * * 1", "每周一生成周报")
        jobs = list_cron_jobs()
        self.assertTrue(any(j["job_id"] == "cj-1" for j in jobs))
        delete_cron_job("cj-1")

    def test_save_and_get_cron_job(self):
        from backend.state_store import save_cron_job, get_cron_job, delete_cron_job
        save_cron_job("cj-2", "30 8 1 * *", "月初数据巡检")
        job = get_cron_job("cj-2")
        self.assertIsNotNone(job)
        self.assertEqual(job["cron_expr"], "30 8 1 * *")
        self.assertEqual(job["status"], "active")
        delete_cron_job("cj-2")

    def test_list_cron_jobs_filtered(self):
        from backend.state_store import (
            save_cron_job, list_cron_jobs, update_cron_job_status, delete_cron_job,
        )
        import uuid
        uid = uuid.uuid4().hex[:8]
        save_cron_job(f"cj-a-{uid}", "0 9 * * *", "active job")
        save_cron_job(f"cj-p-{uid}", "0 12 * * *", "paused job", status="paused")

        active = list_cron_jobs(status_filter="active")
        paused = list_cron_jobs(status_filter="paused")
        self.assertTrue(any(j["job_id"] == f"cj-a-{uid}" for j in active))
        self.assertTrue(any(j["job_id"] == f"cj-p-{uid}" for j in paused))

        delete_cron_job(f"cj-a-{uid}")
        delete_cron_job(f"cj-p-{uid}")

    def test_update_cron_job_status(self):
        from backend.state_store import (
            save_cron_job, get_cron_job, update_cron_job_status, delete_cron_job,
        )
        save_cron_job("cj-status", "0 * * * *", "status test")
        update_cron_job_status("cj-status", "paused")
        job = get_cron_job("cj-status")
        self.assertEqual(job["status"], "paused")
        delete_cron_job("cj-status")

    def test_delete_cron_job(self):
        from backend.state_store import save_cron_job, delete_cron_job, get_cron_job
        save_cron_job("cj-del", "0 0 * * *", "to be deleted")
        self.assertTrue(delete_cron_job("cj-del"))
        self.assertIsNone(get_cron_job("cj-del"))
        self.assertFalse(delete_cron_job("does-not-exist"))

    def test_get_active_cron_jobs(self):
        from backend.state_store import (
            save_cron_job, get_active_cron_jobs, delete_cron_job,
        )
        import uuid
        uid = uuid.uuid4().hex[:8]
        save_cron_job(f"cj-active-{uid}", "0 9 * * *", "active")
        save_cron_job(f"cj-paused-{uid}", "0 12 * * *", "paused", status="paused")

        active = get_active_cron_jobs()
        self.assertTrue(any(j["job_id"] == f"cj-active-{uid}" for j in active))
        self.assertFalse(any(j["job_id"] == f"cj-paused-{uid}" for j in active))

        delete_cron_job(f"cj-active-{uid}")
        delete_cron_job(f"cj-paused-{uid}")

    # ── 工具导入和验证 ──

    def test_tool_imports(self):
        from backend.tools.cron_manager import (
            create_cron_job,
            list_cron_jobs,
            get_cron_job_detail,
            delete_cron_job,
            toggle_cron_job,
        )
        for tool in [create_cron_job, list_cron_jobs, get_cron_job_detail,
                      delete_cron_job, toggle_cron_job]:
            self.assertTrue(hasattr(tool, 'invoke'))

    def test_create_cron_job_invalid_cron(self):
        from backend.tools.cron_manager import create_cron_job
        result = create_cron_job.invoke({"cron_expr": "invalid", "prompt": "test"})
        self.assertIn("Error", result)

    def test_create_cron_job_empty_prompt(self):
        from backend.tools.cron_manager import create_cron_job
        result = create_cron_job.invoke({"cron_expr": "0 9 * * *", "prompt": ""})
        self.assertIn("Error", result)

    def test_list_cron_jobs_tool(self):
        from backend.tools.cron_manager import list_cron_jobs
        result = list_cron_jobs.invoke({})
        self.assertIsInstance(result, str)

    def test_get_cron_job_detail_not_found(self):
        from backend.tools.cron_manager import get_cron_job_detail
        result = get_cron_job_detail.invoke({"job_id": "nonexistent"})
        self.assertIn("未找到", result)

    def test_delete_cron_job_not_found(self):
        from backend.tools.cron_manager import delete_cron_job
        result = delete_cron_job.invoke({"job_id": "nonexistent"})
        self.assertIn("未找到", result)

    def test_toggle_cron_job_not_found(self):
        from backend.tools.cron_manager import toggle_cron_job
        result = toggle_cron_job.invoke({"job_id": "nonexistent"})
        self.assertIn("未找到", result)


if __name__ == "__main__":
    unittest.main()
