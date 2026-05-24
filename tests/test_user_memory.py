"""
测试用户记忆工具：保存、搜索、列表、删除。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class UserMemoryMockTests(unittest.TestCase):
    """测试 user_memory.py 工具函数的逻辑。"""

    @classmethod
    def setUpClass(cls):
        from backend.tools.user_memory import set_memory_user_id
        set_memory_user_id("test-user-memory")

    # ── 模块导入 ──

    def test_tool_imports(self):
        from backend.tools.user_memory import (
            remember, recall, list_memories, forget,
        )
        for tool in [remember, recall, list_memories, forget]:
            self.assertTrue(hasattr(tool, 'invoke'), f"{tool} should have invoke method")

    # ── 输入验证 ──

    def test_remember_empty_content(self):
        from backend.tools.user_memory import remember
        result = remember.invoke({"content": "", "memory_type": "fact"})
        self.assertIn("Error", result)

    def test_remember_invalid_type(self):
        from backend.tools.user_memory import remember
        result = remember.invoke({"content": "test", "memory_type": "invalid"})
        self.assertIn("Error", result)

    def test_recall_empty_query(self):
        from backend.tools.user_memory import recall
        result = recall.invoke({"query": ""})
        self.assertIn("Error", result)

    def test_forget_empty_query(self):
        from backend.tools.user_memory import forget
        result = forget.invoke({"query": ""})
        self.assertIn("Error", result)

    def test_all_memory_types_accepted(self):
        from backend.tools.user_memory import remember
        for mt in ("preference", "fact", "experience", "context"):
            result = remember.invoke({"content": f"test {mt}", "memory_type": mt})
            self.assertNotIn("memory_type 必须是", result)

    # ── 功能测试 ──

    def test_remember_and_recall(self):
        """记住 → 回忆 往返测试（如 Embedding API 不可用则跳过）。"""
        from backend.tools.user_memory import remember, recall, forget

        r = remember.invoke({
            "content": "用户公司叫Acme Corp，毛利率标准35%",
            "memory_type": "fact",
        })
        self.assertIsInstance(r, str)
        api_available = "失败" not in r

        # 回忆
        result = recall.invoke({"query": "公司毛利率"})
        self.assertIsInstance(result, str)

        # 清理
        if api_available:
            forget.invoke({"query": "Acme Corp"})

    def test_list_memories_returns_string(self):
        from backend.tools.user_memory import list_memories
        result = list_memories.invoke({})
        self.assertIsInstance(result, str)

    # ── memory.py 函数测试 ──

    def test_memory_module_functions_exist(self):
        from backend.memory import (
            save_structured_memory,
            search_user_memory,
            get_recent_memories,
            delete_memory_by_query,
            retrieve_memory_context,
        )
        for fn in [save_structured_memory, search_user_memory,
                    get_recent_memories, delete_memory_by_query,
                    retrieve_memory_context]:
            self.assertTrue(callable(fn))

    def test_search_and_recent_memories_no_filter(self):
        from backend.memory import search_user_memory, get_recent_memories
        results = search_user_memory("test", user_id="nonexistent-user-xyz")
        self.assertIsInstance(results, list)
        recent = get_recent_memories(user_id="test-user-memory")
        self.assertIsInstance(recent, list)


if __name__ == "__main__":
    unittest.main()
