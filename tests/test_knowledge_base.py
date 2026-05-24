"""
测试知识库工具：分块、搜索、添加、删除。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class KnowledgeBaseMockTests(unittest.TestCase):
    """测试 knowledge_base.py 工具函数的逻辑。"""

    def setUp(self):
        import backend.memory as mem
        self.mem = mem

    # ── 分块逻辑 ──

    def test_split_text_short(self):
        chunks = self.mem._split_text("hello world", chunk_size=500)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "hello world")

    def test_split_text_long(self):
        text = "第一段。" * 200
        chunks = self.mem._split_text(text, chunk_size=200)
        self.assertTrue(len(chunks) > 1)
        combined = "".join(chunks)
        self.assertEqual(len(combined), len(text))

    def test_split_text_exact_size(self):
        text = "a" * 100
        chunks = self.mem._split_text(text, chunk_size=100)
        self.assertEqual(len(chunks), 1)

    # ── 模块导入 ──

    def test_tool_imports(self):
        from backend.tools.knowledge_base import (
            list_knowledge_files,
            search_knowledge_base,
            add_to_knowledge_base,
            remove_from_knowledge_base,
        )
        for tool in [list_knowledge_files, search_knowledge_base,
                      add_to_knowledge_base, remove_from_knowledge_base]:
            self.assertTrue(hasattr(tool, 'invoke'), f"{tool} should have invoke method")

    # ── 输入验证 ──

    def test_search_knowledge_base_empty_query(self):
        from backend.tools.knowledge_base import search_knowledge_base
        result = search_knowledge_base.invoke({"query": ""})
        self.assertIn("Error", result)

    def test_add_to_knowledge_base_empty_content(self):
        from backend.tools.knowledge_base import add_to_knowledge_base
        result = add_to_knowledge_base.invoke({"content": "", "source_name": "test"})
        self.assertIn("Error", result)

    def test_add_to_knowledge_base_empty_source(self):
        from backend.tools.knowledge_base import add_to_knowledge_base
        result = add_to_knowledge_base.invoke({"content": "test", "source_name": ""})
        self.assertIn("Error", result)

    def test_remove_from_knowledge_base_empty_source(self):
        from backend.tools.knowledge_base import remove_from_knowledge_base
        result = remove_from_knowledge_base.invoke({"source_name": ""})
        self.assertIn("Error", result)

    # ── 功能测试（可能使用真实或 mock ChromaDB）──

    def test_list_knowledge_files_returns_string(self):
        from backend.tools.knowledge_base import list_knowledge_files
        result = list_knowledge_files.invoke({})
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_search_knowledge_returns_string(self):
        from backend.tools.knowledge_base import search_knowledge_base
        result = search_knowledge_base.invoke({"query": "test query"})
        self.assertIsInstance(result, str)

    def test_add_and_remove_knowledge(self):
        """添加 → 搜索 → 删除（如 Embedding API 不可用则跳过写操作）。"""
        from backend.tools.knowledge_base import (
            add_to_knowledge_base,
            search_knowledge_base,
            remove_from_knowledge_base,
        )
        source = f"test_e2e_{os.urandom(4).hex()}"
        # 添加
        add_result = add_to_knowledge_base.invoke({
            "content": "Spectra是一个多Agent数据分析平台，支持FastAPI和Vue 3",
            "source_name": source,
        })
        self.assertIsInstance(add_result, str)
        api_available = "失败" not in add_result

        # 搜索（无论 API 是否可用都应返回字符串）
        search_result = search_knowledge_base.invoke({"query": "Spectra是什么"})
        self.assertIsInstance(search_result, str)

        # 清理（仅在 API 可用时）
        if api_available:
            del_result = remove_from_knowledge_base.invoke({"source_name": source})
            self.assertIn(source, del_result)

    # ── memory.py 函数测试 ──

    def test_memory_module_functions_exist(self):
        self.assertTrue(callable(self.mem.add_knowledge_document))
        self.assertTrue(callable(self.mem.search_knowledge))
        self.assertTrue(callable(self.mem.list_knowledge_sources))
        self.assertTrue(callable(self.mem.remove_knowledge_source))
        self.assertTrue(callable(self.mem._split_text))


if __name__ == "__main__":
    unittest.main()
