"""
报告导出器单元测试。

不依赖网络。验证：
- markdown → docx/pdf 整体跑通
- chart PNG（base64 dataURL）能被嵌入
- 旧入口（messages 数组）退化为最后一条 assistant 消息
- 裸 ECharts JSON 块能消费 charts 列表
- markdown 第一个 H1 优先作为最终标题
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path

# 用 Pillow 生成一张极小的 PNG，作为 chart dataURL 的输入。
from PIL import Image

from backend.report_generator import (
    generate_report,
    parse_markdown_blocks,
    _coerce_to_markdown,
    _extract_first_h1,
)


def _tiny_png_data_url() -> str:
    img = Image.new("RGB", (40, 30), color=(0, 102, 204))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class CoerceTests(unittest.TestCase):
    def test_string_passthrough(self):
        self.assertEqual(_coerce_to_markdown("# Hello"), "# Hello")

    def test_messages_takes_last_assistant_nonempty(self):
        messages = [
            {"role": "user", "content": "ping"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": "## final\n正文。"},
        ]
        self.assertEqual(_coerce_to_markdown(messages), "## final\n正文。")

    def test_messages_with_no_assistant_falls_back(self):
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(_coerce_to_markdown(messages), "hi")

    def test_extract_first_h1(self):
        self.assertEqual(_extract_first_h1("# Title\nbody"), "Title")
        self.assertEqual(_extract_first_h1("body without h1"), "")
        self.assertEqual(_extract_first_h1("## Sub\n# Real Title"), "Real Title")


class ParseBlocksTests(unittest.TestCase):
    def test_headings_and_paragraphs(self):
        md = "# H1\n\n## H2\n\n正文段落 1\n继续行。\n\n正文段落 2"
        blocks = parse_markdown_blocks(md, {})
        self.assertEqual(blocks[0], {"type": "h1", "text": "H1"})
        self.assertEqual(blocks[1], {"type": "h2", "text": "H2"})
        # 段落 1 多行被合并
        self.assertEqual(blocks[2]["type"], "p")
        self.assertIn("正文段落 1", blocks[2]["text"])
        self.assertIn("继续行", blocks[2]["text"])

    def test_bullet_list(self):
        md = "- one\n- two\n- three"
        blocks = parse_markdown_blocks(md, {})
        self.assertEqual(blocks, [{"type": "ul", "items": ["one", "two", "three"]}])

    def test_ordered_list(self):
        md = "1. a\n2. b\n3. c"
        blocks = parse_markdown_blocks(md, {})
        self.assertEqual(blocks, [{"type": "ol", "items": ["a", "b", "c"]}])

    def test_table(self):
        md = "| col1 | col2 |\n|------|------|\n| a    | b    |\n| c    | d    |"
        blocks = parse_markdown_blocks(md, {})
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "table")
        self.assertEqual(blocks[0]["header"], ["col1", "col2"])
        self.assertEqual(blocks[0]["rows"], [["a", "b"], ["c", "d"]])

    def test_agent_artifact_consumes_chart_in_order(self):
        md = (
            "## 部分 A\n正文。\n"
            "<agentArtifact type=\"echarts\" title=\"A 图\">{\"x\":1}</agentArtifact>\n\n"
            "## 部分 B\n继续。\n"
            "<agentArtifact type=\"echarts\" title=\"B 图\">{\"y\":2}</agentArtifact>\n"
        )
        chart_lookup = {
            "first": {"order": 0, "title": "A 图", "png": b"PNG-A"},
            "second": {"order": 1, "title": "B 图", "png": b"PNG-B"},
        }
        blocks = parse_markdown_blocks(md, chart_lookup)
        images = [b for b in blocks if b["type"] == "image"]
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["png"], b"PNG-A")
        self.assertEqual(images[1]["png"], b"PNG-B")

    def test_bare_echarts_json_consumes_chart(self):
        md = (
            "正文段落。\n\n"
            '{ "tooltip": {}, "xAxis": {"type":"category","data":["a"]}, '
            '"yAxis": {"type":"value"}, "series": [{"type":"bar","data":[1]}] }\n\n'
            "结尾。"
        )
        chart_lookup = {
            "x": {"order": 0, "title": "图", "png": b"BARE-PNG"},
        }
        blocks = parse_markdown_blocks(md, chart_lookup)
        images = [b for b in blocks if b["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["png"], b"BARE-PNG")

    def test_image_fallback_when_chart_missing(self):
        md = '<agentArtifact type="echarts" title="orphan">{}</agentArtifact>'
        blocks = parse_markdown_blocks(md, {})  # no chart for this placeholder
        images = [b for b in blocks if b["type"] == "image"]
        self.assertEqual(len(images), 1)
        self.assertIsNone(images[0]["png"])
        self.assertEqual(images[0]["title"], "orphan")
        self.assertEqual(images[0]["fallback_index"], 1)


class GenerateReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # ARTIFACTS_DIR 由 ensure_directories 创建；测试不真正断言路径，
        # 只断言文件落地了。
        self.cleanup_paths: list[Path] = []

    def tearDown(self):
        for p in self.cleanup_paths:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        self.tmp.cleanup()

    def _check_file_created(self, abs_path: str):
        p = Path(abs_path)
        self.cleanup_paths.append(p)
        self.assertTrue(p.exists())
        self.assertGreater(p.stat().st_size, 100)

    def test_docx_generation_with_chart(self):
        md = (
            "# 全球 AI 市场报告\n\n"
            "## 市场规模\n"
            "**2024 年** 全球 AI 市场达到 *5995 亿元*。\n\n"
            '<agentArtifact type="echarts" title="规模趋势">{"x":1}</agentArtifact>\n\n'
            "## 关键发现\n"
            "- 大模型占主导\n"
            "- 应用层增速最快\n"
            "- 基础层投资偏少\n"
        )
        png_url = _tiny_png_data_url()
        result = generate_report(
            "docx",
            "Spectra 测试报告",
            md,
            thread_id="_unit_test",
            charts=[{"chartId": "any", "title": "规模趋势", "dataUrl": png_url}],
            sources=[
                {"index": 1, "title": "示例来源", "url": "https://example.com/a"},
                {"index": 2, "title": "示例来源 2", "url": "https://example.com/b"},
            ],
        )
        self._check_file_created(result["absolute_path"])
        # 文件名应该来自 markdown H1
        self.assertIn("全球 AI 市场报告", result["filename"])

    def test_pdf_generation_with_chart(self):
        md = (
            "## 摘要\n\n"
            "正文段落。\n\n"
            '<agentArtifact type="echarts" title="趋势">{}</agentArtifact>\n\n'
            "1. 第一\n2. 第二\n"
        )
        png_url = _tiny_png_data_url()
        result = generate_report(
            "pdf",
            "兜底标题",  # 没 H1 时使用
            md,
            thread_id="_unit_test_pdf",
            charts=[{"chartId": "c1", "title": "趋势", "dataUrl": png_url}],
        )
        self._check_file_created(result["absolute_path"])
        # 没 H1 → 使用传入 title
        self.assertIn("兜底标题", result["filename"])

    def test_legacy_messages_input_takes_last_assistant(self):
        messages = [
            {"role": "user", "content": "请分析"},
            {"role": "assistant", "content": "中间过程..."},
            {"role": "user", "content": "导出"},
            {"role": "assistant", "content": "# 最终报告\n正文。"},
        ]
        result = generate_report(
            "docx",
            "fallback",
            messages,
            thread_id="_unit_legacy",
        )
        self._check_file_created(result["absolute_path"])
        self.assertIn("最终报告", result["filename"])


if __name__ == "__main__":
    unittest.main()
