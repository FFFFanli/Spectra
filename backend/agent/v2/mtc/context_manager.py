"""
ContextManager —— 上下文压缩管理。

当 LLM 调用历史 token 数累计超过模型上下文窗口的 70% 时触发压缩：
保留 system prompt + 最近 5 条消息 + Plan 当前快照 + 所有 Artifact 摘要列表，丢弃其余消息。

满足：R12.3
"""

from __future__ import annotations

from typing import Any, Optional


class ContextManager:
    """管理 LLM 对话上下文的压缩与截断。"""

    # 上下文窗口使用率阈值（超过此比例触发压缩）
    COMPRESSION_THRESHOLD = 0.70
    # 压缩后保留的最近消息数
    KEEP_RECENT_MESSAGES = 5

    def __init__(self, model_context_window: int = 128000):
        self.model_context_window = model_context_window
        self._total_input_tokens = 0

    def add_tokens(self, count: int) -> None:
        """累计输入 token 数。"""
        self._total_input_tokens += count

    def should_compress(self) -> bool:
        """判断是否需要触发上下文压缩。"""
        threshold = int(self.model_context_window * self.COMPRESSION_THRESHOLD)
        return self._total_input_tokens >= threshold

    def compress_messages(
        self,
        system_prompt: str,
        messages: list[dict],
        plan_snapshot: Optional[dict] = None,
        artifact_summaries: Optional[list[str]] = None,
    ) -> list[dict]:
        """压缩消息列表：保留 system prompt + 最近 N 条 + Plan 快照 + Artifact 摘要。"""
        compressed = []

        # System prompt
        if system_prompt:
            compressed.append({"role": "system", "content": system_prompt})

        # Plan 快照（注入为 system 补充）
        if plan_snapshot and plan_snapshot.get("steps"):
            steps_text = "\n".join(
                f"- [{s['status']}] {s['description']} ({s.get('assignee_agent_id', '')})"
                for s in plan_snapshot["steps"]
            )
            compressed.append({
                "role": "system",
                "content": f"[当前任务计划]\n{steps_text}",
            })

        # Artifact 摘要
        if artifact_summaries:
            compressed.append({
                "role": "system",
                "content": f"[已生成产物]\n" + "\n".join(artifact_summaries),
            })

        # 最近 N 条消息
        recent = messages[-self.KEEP_RECENT_MESSAGES:] if len(messages) > self.KEEP_RECENT_MESSAGES else messages
        compressed.extend(recent)

        # 重置计数
        self._total_input_tokens = 0

        return compressed

    def reset(self) -> None:
        """重置 token 计数。"""
        self._total_input_tokens = 0
