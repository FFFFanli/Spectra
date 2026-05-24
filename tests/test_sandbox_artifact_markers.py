"""
单元测试：单 agent 沙盒产物 marker 解析。

不依赖网络 / 沙盒。仅测试 SSE 转译层从 execute_python 工具 stdout 中
正确抽出产物事件。
"""

from __future__ import annotations

import json
import unittest

from backend.api import _parse_sandbox_artifact_markers


class ParseSandboxMarkersTests(unittest.TestCase):
    def _decode(self, events: list[dict]) -> list[dict]:
        return [{**e, "data": json.loads(e["data"])} for e in events]

    def test_empty_output(self):
        self.assertEqual(_parse_sandbox_artifact_markers(""), [])
        self.assertEqual(_parse_sandbox_artifact_markers(None), [])

    def test_no_markers_returns_empty(self):
        self.assertEqual(_parse_sandbox_artifact_markers("hello world\n执行成功"), [])

    def test_file_generated_emits_file_event(self):
        out = (
            "✅ 代码执行成功\n"
            "FILE_GENERATED:report_xxxx.docx\n"
            "正文已写入。"
        )
        events = self._decode(_parse_sandbox_artifact_markers(out))

        # 第一条是 artifacts 汇总
        self.assertEqual(events[0]["event"], "artifacts")
        self.assertEqual(events[0]["data"][0]["type"], "file")
        self.assertEqual(events[0]["data"][0]["name"], "report_xxxx.docx")
        self.assertEqual(events[0]["data"][0]["path"], "/files/report_xxxx.docx")

        # 紧跟的 file 事件
        file_events = [e for e in events if e["event"] == "file"]
        self.assertEqual(len(file_events), 1)
        self.assertEqual(file_events[0]["data"]["url"], "/files/report_xxxx.docx")
        self.assertEqual(file_events[0]["data"]["name"], "report_xxxx.docx")
        self.assertEqual(file_events[0]["data"]["format"], "DOCX")

    def test_report_pdf_marker(self):
        out = "REPORT_GENERATED:report_abc.pdf"
        events = self._decode(_parse_sandbox_artifact_markers(out))

        types_seen = [e["event"] for e in events]
        self.assertIn("artifacts", types_seen)
        self.assertIn("file", types_seen)

        artifact = next(e for e in events if e["event"] == "artifacts")
        self.assertEqual(artifact["data"][0]["type"], "report_pdf")

        file_evt = next(e for e in events if e["event"] == "file")
        self.assertEqual(file_evt["data"]["format"], "PDF")

    def test_report_docx_marker(self):
        out = "REPORT_GENERATED:summary.docx"
        events = self._decode(_parse_sandbox_artifact_markers(out))
        artifact = next(e for e in events if e["event"] == "artifacts")
        self.assertEqual(artifact["data"][0]["type"], "report_docx")

    def test_chart_marker_does_not_emit_file(self):
        """图表 HTML/PNG 走 artifacts 通道（前端已有 taskArtifacts 渲染），
        但不应当作'下载卡片'再下发 file 事件。"""
        out = (
            "CHART_GENERATED:chart_aabbcc.html\n"
            "CHART_PNG_GENERATED:chart_aabbcc.png"
        )
        events = self._decode(_parse_sandbox_artifact_markers(out))

        # 应有一条 artifacts 汇总，包含两条产物
        artifact_evts = [e for e in events if e["event"] == "artifacts"]
        self.assertEqual(len(artifact_evts), 1)
        types = [a["type"] for a in artifact_evts[0]["data"]]
        self.assertIn("chart_html", types)
        self.assertIn("chart_png", types)

        # 不应有 file 事件
        file_evts = [e for e in events if e["event"] == "file"]
        self.assertEqual(file_evts, [])

    def test_mixed_chart_and_file(self):
        out = (
            "CHART_PNG_GENERATED:chart_x.png\n"
            "FILE_GENERATED:result.xlsx"
        )
        events = self._decode(_parse_sandbox_artifact_markers(out))

        # 一条 artifacts 包含两个项
        artifact = next(e for e in events if e["event"] == "artifacts")
        self.assertEqual(len(artifact["data"]), 2)

        # 仅 xlsx 触发 file 事件
        file_evts = [e for e in events if e["event"] == "file"]
        self.assertEqual(len(file_evts), 1)
        self.assertEqual(file_evts[0]["data"]["name"], "result.xlsx")

    def test_multiple_files_each_get_event(self):
        out = (
            "FILE_GENERATED:a.docx\n"
            "FILE_GENERATED:b.xlsx\n"
            "FILE_GENERATED:c.pdf"
        )
        events = self._decode(_parse_sandbox_artifact_markers(out))

        artifact = next(e for e in events if e["event"] == "artifacts")
        self.assertEqual(len(artifact["data"]), 3)

        file_evts = [e for e in events if e["event"] == "file"]
        self.assertEqual(len(file_evts), 3)
        names = sorted(e["data"]["name"] for e in file_evts)
        self.assertEqual(names, ["a.docx", "b.xlsx", "c.pdf"])

    def test_path_with_subdirectory(self):
        out = "REPORT_GENERATED:thread_abc/report_v1.pdf"
        events = self._decode(_parse_sandbox_artifact_markers(out))

        file_evt = next(e for e in events if e["event"] == "file")
        self.assertEqual(file_evt["data"]["url"], "/files/thread_abc/report_v1.pdf")
        self.assertEqual(file_evt["data"]["name"], "report_v1.pdf")


if __name__ == "__main__":
    unittest.main()
