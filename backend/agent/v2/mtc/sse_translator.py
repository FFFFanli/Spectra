"""
SSE Translator —— 内部事件 → SSE 事件映射。

保持 Legacy_Team_Event 全部可用，新增 MTC_SSE_Event。
确保 done 为最后事件。

满足：R9
"""

from __future__ import annotations

from typing import Any


class SSETranslator:
    """将 Runtime 内部事件翻译为 SSE (event, data) 对。"""

    # Legacy 事件（保持兼容）
    LEGACY_EVENTS = {
        "supervisor_decision",
        "agent_message",
        "reply",
        "done",
        "error",
        "usage",
        "artifacts",
        "file",
    }

    # MTC 新增事件
    MTC_EVENTS = {
        "plan_created",
        "plan_updated",
        "plan_revised",
        "step_started",
        "step_completed",
        "step_failed",
        "member_status",
        "task_pending",
        "task_progress",
        "task_completed",
        "task_failed",
        "file_parsed",
        "workspace_artifact_added",
    }

    def translate(self, internal_event: dict) -> dict:
        """内部事件 → {"event": str, "data": str}。"""
        event_type = internal_event.get("event", "message")
        payload = internal_event.get("data", {})

        # 所有 payload 序列化为 JSON 字符串
        import json

        return {
            "event": event_type,
            "data": json.dumps(payload, ensure_ascii=False),
        }

    def build_done_event(
        self,
        thread_id: str,
        plan_snapshot: dict,
        artifacts: list[dict],
        background_tasks: list[dict],
        runtime_variant: str = "mtc",
    ) -> dict:
        """构建 done 事件（确保包含所有必需字段）。"""
        import json

        return {
            "event": "done",
            "data": json.dumps({
                "thread_id": thread_id,
                "plan": plan_snapshot,
                "artifacts": artifacts,
                "background_tasks": background_tasks,
                "runtime_variant": runtime_variant,
            }, ensure_ascii=False),
        }

    def is_mtc_event(self, event_type: str) -> bool:
        """判断是否为 MTC 新增事件。"""
        return event_type in self.MTC_EVENTS

    def is_legacy_event(self, event_type: str) -> bool:
        """判断是否为 Legacy 事件。"""
        return event_type in self.LEGACY_EVENTS
