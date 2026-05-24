"""
测试用户交互工具：ask_user / request_confirmation。
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class UserInteractionTests(unittest.TestCase):
    """测试 user_interaction.py 工具函数的逻辑。"""

    def setUp(self):
        from backend.tools.user_interaction import clear_pending_question
        clear_pending_question()

    # ── 模块导入 ──

    def test_tool_imports(self):
        from backend.tools.user_interaction import ask_user, request_confirmation
        for tool in [ask_user, request_confirmation]:
            self.assertTrue(hasattr(tool, 'invoke'))

    # ── ask_user ──

    def test_ask_user_basic(self):
        from backend.tools.user_interaction import ask_user, get_pending_question
        result = ask_user.invoke({"question": "应该用哪种方法处理缺失值？"})
        self.assertIn("需要用户确认", result)
        self.assertIn("缺失值", result)

        question = get_pending_question()
        self.assertIsNotNone(question)
        self.assertEqual(question["question"], "应该用哪种方法处理缺失值？")
        self.assertIsNone(question["options"])

    def test_ask_user_with_options(self):
        from backend.tools.user_interaction import ask_user, get_pending_question
        result = ask_user.invoke({
            "question": "选哪种图表？",
            "options": '["柱状图","折线图","饼图"]',
        })
        self.assertIn("选项", result)
        self.assertIn("柱状图", result)

        question = get_pending_question()
        self.assertEqual(len(question["options"]), 3)
        self.assertEqual(question["options"][0], "柱状图")

    def test_ask_user_invalid_json_options(self):
        """无效 JSON 选项时，options 为 None。"""
        from backend.tools.user_interaction import ask_user, get_pending_question
        result = ask_user.invoke({
            "question": "test?",
            "options": "not valid json",
        })
        question = get_pending_question()
        self.assertIsNone(question["options"])  # 解析失败，当无选项

    def test_ask_user_empty_content(self):
        """空问题返回错误。"""
        from backend.tools.user_interaction import ask_user
        result = ask_user.invoke({"question": ""})
        self.assertIn("Error", result)

    # ── request_confirmation ──

    def test_request_confirmation_basic(self):
        from backend.tools.user_interaction import request_confirmation, get_pending_question
        result = request_confirmation.invoke({"message": "删除所有缺失数据？"})
        self.assertIn("操作确认", result)
        self.assertIn("删除", result)

        question = get_pending_question()
        self.assertIsNotNone(question)
        self.assertEqual(question["type"], "confirmation")

    def test_request_confirmation_empty(self):
        """空消息返回错误。"""
        from backend.tools.user_interaction import request_confirmation
        result = request_confirmation.invoke({"message": ""})
        self.assertIn("Error", result)

    # ── ContextVar 隔离 ──

    def test_pending_question_cleared(self):
        from backend.tools.user_interaction import (
            ask_user, get_pending_question, clear_pending_question,
        )
        ask_user.invoke({"question": "test?"})
        self.assertIsNotNone(get_pending_question())
        clear_pending_question()
        self.assertIsNone(get_pending_question())

    def test_get_pending_question_default(self):
        from backend.tools.user_interaction import get_pending_question
        self.assertIsNone(get_pending_question())


if __name__ == "__main__":
    unittest.main()
