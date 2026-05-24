"""
请求级上下文。

用 ContextVar 隔离每个 HTTP 请求的状态，避免 set_request_model 这种全局态在多用户并发时互相覆盖。

ContextVar 在 asyncio 下天然按 task 隔离 —— FastAPI 每个请求都是独立 task，
对 ContextVar 的 set 只影响当前请求所在 task 的 context 副本，不会泄漏到其他请求。
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

from langchain_core.callbacks import UsageMetadataCallbackHandler

# 当前请求选定的模型名；空串表示回落到 SPECTRA_SELECTED_MODEL 环境变量
_request_model: ContextVar[str] = ContextVar("spectra_request_model", default="")

# 当前请求的 token 累计 callback；同一请求内所有 LLM 调用共享，跨请求隔离
_request_usage: ContextVar[Optional[UsageMetadataCallbackHandler]] = ContextVar(
    "spectra_request_usage", default=None
)

# 用户消息附带的图表 PNG（从前端 echarts.getDataURL 收集而来）
# 结构：[{"name": "chart_1.png", "title": "...", "png_bytes": b"..."}]
# 沙盒执行 (_run_code_e2b) 会把这些文件写到沙盒根目录，供 LLM 在 python-docx
# 中直接 doc.add_picture('chart_1.png') 嵌入，避免在沙盒里重画图。
_request_attached_charts: ContextVar[list] = ContextVar(
    "spectra_request_attached_charts", default=[]
)


def begin_request(model: str = "") -> UsageMetadataCallbackHandler:
    """在请求入口调用，设置本次请求的 model 与 usage callback。

    返回新建的 UsageMetadataCallbackHandler，便于上层在请求结束时读取 token 统计。
    """
    cleaned = (model or "").strip()
    _request_model.set(cleaned)
    handler = UsageMetadataCallbackHandler()
    _request_usage.set(handler)
    # 默认清空附带图表（每个请求独立）
    _request_attached_charts.set([])
    return handler


def set_attached_charts(charts: list) -> None:
    """设置本次请求的附带图表 PNG 列表。

    入参约定：
        [{"name": "chart_1.png", "title": "...", "png_bytes": b"..."}]
    name 必须以 .png 结尾；png_bytes 是已解码的二进制；title 仅作元信息。
    """
    _request_attached_charts.set(list(charts or []))


def get_attached_charts() -> list:
    """返回本次请求的附带图表列表（可能为空）。"""
    return list(_request_attached_charts.get() or [])


# 导出时前端传过来的报告正文（最近一条 assistant 消息的 content）
_request_export_content: ContextVar[dict] = ContextVar(
    "spectra_request_export_content", default={}
)

# 最近一条 assistant 回复正文（每次 agent 流式回复结束时更新，供导出 fallback 使用）
_last_assistant_reply: ContextVar[str] = ContextVar(
    "spectra_last_assistant_reply", default=""
)


def set_export_content(data: dict) -> None:
    """设置本次请求的导出内容。

    入参约定：{"content": "markdown 正文", "title": "报告标题"}
    """
    _request_export_content.set(dict(data or {}))


def get_export_content() -> dict:
    """返回本次请求的导出内容（可能为空 dict）。"""
    return dict(_request_export_content.get() or {})


def set_last_assistant_reply(text: str) -> None:
    """缓存最近一条 assistant 回复正文，供后续导出请求 fallback 使用。"""
    _last_assistant_reply.set(str(text or ""))


def get_last_assistant_reply() -> str:
    """返回最近一条 assistant 回复正文（可能为空）。"""
    return _last_assistant_reply.get() or ""


def get_request_model() -> str:
    """返回本次请求绑定的模型名，未绑定时返回空串。"""
    return _request_model.get()


def get_request_usage_callback() -> Optional[UsageMetadataCallbackHandler]:
    """返回本次请求的 usage callback，未初始化时返回 None。"""
    return _request_usage.get()


def get_usage_summary() -> dict:
    """汇总本次请求所有 LLM 调用的 token 统计。

    返回结构：
    {
        "by_model": {model_name: {input_tokens, output_tokens, total_tokens, ...}},
        "total": {input_tokens, output_tokens, total_tokens}
    }
    """
    handler = _request_usage.get()
    if handler is None or not getattr(handler, "usage_metadata", None):
        return {"by_model": {}, "total": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}

    by_model: dict[str, dict] = {}
    total_input = total_output = total_total = 0

    for model_name, usage in handler.usage_metadata.items():
        # UsageMetadata 是 TypedDict，以 dict 操作即可
        usage_dict = dict(usage) if not isinstance(usage, dict) else usage
        by_model[model_name] = usage_dict
        total_input += int(usage_dict.get("input_tokens", 0) or 0)
        total_output += int(usage_dict.get("output_tokens", 0) or 0)
        total_total += int(usage_dict.get("total_tokens", 0) or 0)

    return {
        "by_model": by_model,
        "total": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_total or (total_input + total_output),
        },
    }
