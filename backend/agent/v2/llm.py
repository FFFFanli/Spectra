"""
v2 的 LLM 工厂。本模块是项目内 LLM 创建的唯一入口。

支持 provider：
- DashScope (qwen-* 模型)
- OpenAI (gpt-* / o1 / o3)
- DeepSeek（deepseek-* 模型，启用 thinking 模式）

ContextVar 协作：
- 通过 backend.request_context.get_request_model() 取本次请求选定的 model
- 通过 backend.request_context.get_request_usage_callback() 取 token 累计 callback
  并自动 bind 到 LLM 上
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, BaseMessage

from backend.request_context import (
    get_request_model as _get_request_model,
    get_request_usage_callback as _get_request_usage_callback,
)


__all__ = [
    "DeepSeekV4ChatOpenAI",
    "_create_llm",
    "get_llm",
    "_get_model_config",
    "_resolve_model",
]


class DeepSeekV4ChatOpenAI(ChatOpenAI):
    """ChatOpenAI 子类，兼容 DeepSeek V4 thinking 模式。

    DeepSeek V4 在 thinking 模式下（默认开启），assistant 消息响应中会包含
    reasoning_content 字段。根据官方文档要求：
    - 未发生工具调用时：reasoning_content 可传可不传（API 会忽略）
    - 发生工具调用后：后续所有请求必须回传 reasoning_content，否则 400 报错

    本子类负责：
    1. 非流式：从 API 原始响应中捕获 reasoning_content 并存入 AIMessage.additional_kwargs
    2. 流式：从 SSE chunk 的 delta.reasoning_content 累积到 AIMessageChunk.additional_kwargs
       （langchain_openai 1.x 的 _convert_delta_to_message_chunk 会丢弃该字段）
    3. 在后续请求中将 reasoning_content 序列化回 assistant 消息体中回传
    """

    def _create_chat_result(self, response, generation_info=None):
        chat_result = super()._create_chat_result(response, generation_info)
        try:
            rc = None
            choice = response.choices[0]
            msg = choice.message

            if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                rc = msg.reasoning_content
            if not rc and hasattr(msg, "model_extra"):
                rc = (msg.model_extra or {}).get("reasoning_content")
            if not rc:
                raw = response.model_dump()
                rc = raw.get("choices", [{}])[0].get("message", {}).get("reasoning_content")

            if rc and chat_result.generations:
                for gen in chat_result.generations:
                    gen.message.additional_kwargs["reasoning_content"] = rc
        except Exception:
            pass
        return chat_result

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ):
        """覆盖流式分支：把 delta.reasoning_content 写入 message.additional_kwargs。

        langchain_openai 1.x 的 _convert_delta_to_message_chunk 不识别
        reasoning_content，会在 chunk 转换阶段直接丢弃。这里在父类生成的
        ChatGenerationChunk 上补上该字段；AIMessageChunk 合并时 additional_kwargs
        中相同 key 的字符串会被自动拼接，最终累积出完整推理内容。
        """
        gen_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen_chunk is None:
            return gen_chunk
        try:
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
            if choices:
                first = choices[0]
                # 兼容两种位置：标准 chat.completions 流式在 delta 里，
                # 部分 provider 在最终 chunk 的 message 字段里给完整 reasoning_content
                rc = None
                delta = first.get("delta") or {}
                if isinstance(delta, dict):
                    rc = delta.get("reasoning_content")
                if not rc:
                    msg = first.get("message") or {}
                    if isinstance(msg, dict):
                        rc = msg.get("reasoning_content")
                if rc and not isinstance(rc, str):
                    # 极端情况：provider 返回结构化对象，序列化为字符串避免合并报错
                    try:
                        import json as _json
                        rc = _json.dumps(rc, ensure_ascii=False)
                    except Exception:
                        rc = str(rc)
                if rc:
                    gen_chunk.message.additional_kwargs["reasoning_content"] = rc
                    if os.environ.get("SPECTRA_DEBUG_REASONING") == "1":
                        print(f"[DeepSeekV4] chunk reasoning_content captured: {len(rc)} chars")
        except Exception as exc:
            if os.environ.get("SPECTRA_DEBUG_REASONING") == "1":
                print(f"[DeepSeekV4] chunk hook error: {exc}")
        return gen_chunk

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        """在父类构造好 payload 后，把 AIMessage.additional_kwargs 中的
        reasoning_content 注入回对应的 assistant 消息体。

        langchain_openai 1.x 的 _convert_message_to_dict 是模块级函数（不是方法），
        无法通过子类方法覆盖；其默认实现也不会把 reasoning_content 写入请求体。
        因此我们在 _get_request_payload 这一层做事后修补。

        修补依据：按 messages 顺序把 LangChain AIMessage 与 payload["messages"] 中
        role=="assistant" 的条目 1:1 对齐。
        """
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # 仅 chat/completions 路径需要修补；responses API 不走 reasoning_content 字段。
        msgs = payload.get("messages")
        if not isinstance(msgs, list):
            return payload

        try:
            lc_messages = self._convert_input(input_).to_messages()
        except Exception:
            return payload

        # 按位置 1:1 对齐：父类用列表推导式构造 payload["messages"]，顺序与
        # lc_messages 一致。逐个对比；只在 LangChain 侧是 AIMessage 且 OpenAI 侧
        # 是 assistant role 时注入 reasoning_content。
        if len(msgs) == len(lc_messages):
            injected = 0
            assistants = 0
            for entry, lc in zip(msgs, lc_messages):
                if not isinstance(entry, dict) or entry.get("role") != "assistant":
                    continue
                assistants += 1
                if not isinstance(lc, AIMessage):
                    continue
                rc = (lc.additional_kwargs or {}).get("reasoning_content")
                if rc and "reasoning_content" not in entry:
                    entry["reasoning_content"] = rc
                    injected += 1
            if os.environ.get("SPECTRA_DEBUG_REASONING") == "1":
                print(
                    f"[DeepSeekV4] payload patch: assistants={assistants} "
                    f"injected_reasoning_content={injected} total_messages={len(msgs)}"
                )
        else:
            if os.environ.get("SPECTRA_DEBUG_REASONING") == "1":
                print(
                    f"[DeepSeekV4] payload length mismatch: "
                    f"payload_msgs={len(msgs)} lc_messages={len(lc_messages)}"
                )

        return payload


def _resolve_model() -> str:
    """优先使用请求级 ContextVar 覆盖，否则回退到环境变量。"""
    override = _get_request_model()
    if override:
        return override
    return os.environ.get("SPECTRA_SELECTED_MODEL", "qwen3.6-plus").strip()


_MODEL_PROVIDER_LOG: dict[str, bool] = {}


def _get_model_config():
    """根据当前模型名返回 (model, api_key, base_url, extra_kwargs)。

    所有 provider 的 base_url 显式给出，不依赖全局 OPENAI_API_BASE。
    DeepSeek 启用 thinking 模式，reasoning_content 由 DeepSeekV4ChatOpenAI 处理。
    """
    model = _resolve_model()
    extra: dict = {}
    if model.startswith("qwen-"):
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        provider = "DashScope"
    elif model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = None
        provider = "OpenAI"
    elif model.startswith("deepseek-"):
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        base_url = "https://api.deepseek.com/v1"
        provider = "DeepSeek"
        extra["extra_body"] = {"thinking": {"type": "enabled"}}
    else:
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        provider = "DashScope(fallback)"

    log_key = f"{model}/{provider}/{base_url or 'default'}"
    if log_key not in _MODEL_PROVIDER_LOG:
        _MODEL_PROVIDER_LOG[log_key] = True
        thinking_state = (
            "enabled"
            if extra.get("extra_body", {}).get("thinking", {}).get("type") == "enabled"
            else "default"
        )
        print(
            f"[LLM] 模型={model} | Provider={provider} | "
            f"base_url={base_url or '(OpenAI default)'} | thinking={thinking_state}"
        )

    return model, api_key if api_key else "dummy", base_url, extra


def _create_llm(temperature: float = 0.1):
    """v2 的统一 LLM 工厂函数。所有 LLM 创建必须通过此函数。"""
    model, api_key, base_url, extra = _get_model_config()
    kwargs = dict(model=model, api_key=api_key, temperature=temperature)
    if base_url:
        kwargs["base_url"] = base_url
    if extra.get("extra_body"):
        kwargs["extra_body"] = extra["extra_body"]
    if extra.get("model_kwargs"):
        kwargs["model_kwargs"] = extra["model_kwargs"]
    # 自动绑 token usage callback；request_context 没初始化时为 None 即可
    usage_cb = _get_request_usage_callback()
    if usage_cb is not None:
        kwargs["callbacks"] = [usage_cb]
    if model.startswith("deepseek-"):
        # DeepSeek thinking 模式响应慢且长，给一个宽容的 read timeout 与
        # 重试策略，避免上游随机断流直接吞掉本次调用。
        # request_timeout 是 ChatOpenAI 透传给 openai SDK 的总超时；
        # max_retries 由 openai SDK 层面在连接错误（不含 mid-stream cut）时使用。
        kwargs.setdefault("timeout", 300.0)
        kwargs.setdefault("max_retries", 3)
        return DeepSeekV4ChatOpenAI(**kwargs)
    return ChatOpenAI(**kwargs)


def get_llm():
    return _create_llm(temperature=0.1)
