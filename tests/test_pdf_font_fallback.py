"""
CJK 字体运行时补丁测试。

旧版本测试通过 backend.report_templates 生成代码再断言其中包含 CJK 注册逻辑，
模板文件已在 W3 删除（writer 改为 LLM 实时生成 reportlab 代码）。
现在直接测试 _patch_reportlab_cjk_support 这个补丁本身：
喂一段使用 Helvetica 的 reportlab 代码进去，断言补丁注入了字体回退。
"""

import unittest

from backend.agent.v2.infra.executor_impl import _patch_reportlab_cjk_support


SAMPLE_REPORTLAB_CODE = """
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import ParagraphStyle

style = ParagraphStyle('body', fontName='Helvetica', fontSize=12)

def get_font():
    return "Helvetica"

doc = SimpleDocTemplate('out.pdf', pagesize=A4)
doc.build([Paragraph('中文测试', style)])
print("REPORT_GENERATED:out.pdf")
"""


class CJKFontPatchTests(unittest.TestCase):
    def test_patch_injects_helper_and_replaces_helvetica(self):
        patched = _patch_reportlab_cjk_support(SAMPLE_REPORTLAB_CODE)

        # 注入了 helper 函数（以 V1 marker 标识）
        self.assertIn("CJK_FONT_RUNTIME_PATCH_V1", patched)
        # 引入了 UnicodeCIDFont
        self.assertIn("UnicodeCIDFont", patched)
        # 至少把一个直接的 'Helvetica' 写法替换为字体变量
        self.assertIn("_CJK_FONT_NAME or 'Helvetica'", patched)
        # 仍可编译
        compile(patched, "<patched>", "exec")

    def test_patch_is_idempotent(self):
        once = _patch_reportlab_cjk_support(SAMPLE_REPORTLAB_CODE)
        twice = _patch_reportlab_cjk_support(once)
        self.assertEqual(once, twice)

    def test_patch_skips_non_pdf_code(self):
        non_pdf = "import duckdb\nprint('hello')\n"
        # 不含 reportlab 关键字 → 应原样返回
        self.assertEqual(_patch_reportlab_cjk_support(non_pdf), non_pdf)


if __name__ == "__main__":
    unittest.main()
