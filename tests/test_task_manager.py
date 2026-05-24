"""
测试 GTD 任务管理工具：持久化任务 CRUD、层级关系、状态级联。
"""
import unittest
import tempfile
import os
import sys

# 确保 backend 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.state_store import (
    save_gtd_task,
    get_gtd_tasks_by_thread,
    get_gtd_task,
    update_gtd_task,
    update_gtd_task_status,
    delete_gtd_task,
    finish_all_gtd_tasks,
    init_state_store,
)

# 使用临时数据库避免污染正式数据
os.environ["STATE_DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_spectra_state.db")


class TaskManagerDbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from backend.app_paths import DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        init_state_store()

    def setUp(self):
        import uuid
        self.thread_id = f"test-{uuid.uuid4().hex[:8]}"

    def _create_task(self, task_id="t1", title="测试任务", **kwargs):
        save_gtd_task(
            task_id=task_id,
            thread_id=self.thread_id,
            title=title,
            **kwargs,
        )

    # ── 基础 CRUD ──

    def test_save_and_get_task(self):
        self._create_task("t-crud-1", "数据探索")
        task = get_gtd_task("t-crud-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "数据探索")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["priority"], "medium")

    def test_get_tasks_by_thread(self):
        self._create_task("t-thread-a", "任务A")
        self._create_task("t-thread-b", "任务B", sort_order=1)

        # 另一个 thread 的任务
        save_gtd_task(
            task_id="t-other",
            thread_id="other-thread",
            title="其他线程任务",
        )

        tasks = get_gtd_tasks_by_thread(self.thread_id)
        self.assertEqual(len(tasks), 2)

    def test_list_tasks_empty(self):
        tasks = get_gtd_tasks_by_thread("empty-thread")
        self.assertEqual(len(tasks), 0)

    # ── 更新 ──

    def test_update_task_fields(self):
        self._create_task("t-update-1", "原始标题")
        update_gtd_task("t-update-1", title="新标题", priority="urgent", note="加急")
        task = get_gtd_task("t-update-1")
        self.assertEqual(task["title"], "新标题")
        self.assertEqual(task["priority"], "urgent")
        self.assertEqual(task["note"], "加急")

    def test_update_task_status_cascade_to_parent(self):
        # 父任务 + 2 个子任务
        self._create_task("t-parent", "父任务")
        self._create_task("t-child-1", "子任务1", parent_id="t-parent")
        self._create_task("t-child-2", "子任务2", parent_id="t-parent")

        # 完成两个子任务
        update_gtd_task_status("t-child-1", "done")
        update_gtd_task_status("t-child-2", "done")

        # 父任务应该自动变成 done
        parent = get_gtd_task("t-parent")
        self.assertEqual(parent["status"], "done")

    def test_update_task_status_no_cascade_when_child_pending(self):
        self._create_task("t-parent2", "父任务2")
        self._create_task("t-child-a", "子任务A", parent_id="t-parent2")
        self._create_task("t-child-b", "子任务B", parent_id="t-parent2")

        # 只完成一个子任务
        update_gtd_task_status("t-child-a", "done")

        # 父任务应该还是 pending
        parent = get_gtd_task("t-parent2")
        self.assertEqual(parent["status"], "pending")

    # ── 删除 ──

    def test_delete_task_cascade(self):
        self._create_task("t-del-root", "根任务")
        self._create_task("t-del-mid", "中间任务", parent_id="t-del-root")
        self._create_task("t-del-leaf", "叶子任务", parent_id="t-del-mid")

        deleted = delete_gtd_task("t-del-root")
        self.assertEqual(set(deleted), {"t-del-root", "t-del-mid", "t-del-leaf"})

        # 确认全部删除
        for tid in deleted:
            self.assertIsNone(get_gtd_task(tid))

    def test_delete_task_only_self_if_no_children(self):
        self._create_task("t-solo", "独立任务")
        deleted = delete_gtd_task("t-solo")
        self.assertEqual(deleted, ["t-solo"])
        self.assertIsNone(get_gtd_task("t-solo"))

    # ── 批量完成 ──

    def test_finish_all_tasks(self):
        self._create_task("t-fin-1", "任务1")
        self._create_task("t-fin-2", "任务2", status="in_progress")
        self._create_task("t-fin-3", "任务3", status="done")

        count = finish_all_gtd_tasks(self.thread_id)
        self.assertEqual(count, 2)  # t-fin-1 和 t-fin-2 变成 done

        self.assertEqual(get_gtd_task("t-fin-1")["status"], "done")
        self.assertEqual(get_gtd_task("t-fin-2")["status"], "done")
        self.assertEqual(get_gtd_task("t-fin-3")["status"], "done")  # 没变

    def test_finish_all_empty_thread(self):
        count = finish_all_gtd_tasks("nonexistent-thread")
        self.assertEqual(count, 0)

    # ── 边界 ──

    def test_get_nonexistent_task(self):
        self.assertIsNone(get_gtd_task("does-not-exist"))

    def test_update_nonexistent_task(self):
        # 不应该抛异常
        update_gtd_task("does-not-exist", title="x")
        # 静默忽略

    def test_delete_nonexistent_task(self):
        # 不应该抛异常
        deleted = delete_gtd_task("does-not-exist")
        self.assertEqual(deleted, ["does-not-exist"])

    def test_parent_child_hierarchy(self):
        self._create_task("t-root", "项目")
        self._create_task("t-sub1", "子项目1", parent_id="t-root", sort_order=0)
        self._create_task("t-sub2", "子项目2", parent_id="t-root", sort_order=1)
        self._create_task("t-sub-sub", "孙项目", parent_id="t-sub1")

        all_tasks = get_gtd_tasks_by_thread(self.thread_id)
        self.assertEqual(len(all_tasks), 4)

        # 验证层级关系
        root = get_gtd_task("t-root")
        self.assertIsNone(root["parent_id"])
        sub1 = get_gtd_task("t-sub1")
        self.assertEqual(sub1["parent_id"], "t-root")
        sub_sub = get_gtd_task("t-sub-sub")
        self.assertEqual(sub_sub["parent_id"], "t-sub1")


if __name__ == "__main__":
    unittest.main()
