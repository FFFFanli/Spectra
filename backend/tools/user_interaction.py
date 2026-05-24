"""
用户交互工具：ask_user / request_confirmation。

允许 Agent 在分析过程中主动向用户提问、请求决策或确认。
参考 LobeChat User Interaction 工具的设计。
"""

from langchain_core.tools import tool

_pending_question: dict | None = None


def get_pending_question() -> dict | None:
    """获取当前待处理的用户问题（供 SSE 事件循环使用）。"""
    return _pending_question


def clear_pending_question() -> None:
    global _pending_question
    _pending_question = None


@tool
def ask_user(question: str, options: str = "") -> str:
    """向用户提问，在需要用户决策或信息不足时使用。请勿滥用——只在真正需要用户输入时才调用。

    Args:
        question: 要问用户的问题。要清晰、具体，让用户容易回答。
        options: 可选。JSON 字符串数组，提供预设选项让用户选择。
                 示例: '["用均值填充","用中位数填充","删除缺失值所在行"]'
                 如果不提供选项，用户可自由回答。
    """
    import json

    if not question or not question.strip():
        return "Error: question 不能为空"

    q = question.strip()
    opts = None
    if options and options.strip():
        try:
            parsed = json.loads(options.strip())
            if isinstance(parsed, list) and len(parsed) > 0:
                opts = [str(o) for o in parsed]
        except json.JSONDecodeError:
            pass  # 解析失败就当没有选项

    global _pending_question
    _pending_question = {"question": q, "options": opts}

    lines = [
        "—— 需要用户确认 ——",
        f"问题: {q}",
    ]
    if opts:
        lines.append(f"选项: {', '.join(opts)}")
    lines.append("请在对话中回复你的选择。")
    return "\n".join(lines)


@tool
def request_confirmation(message: str) -> str:
    """在执行不可逆操作前请求用户确认。适用于：删除数据、覆盖文件、发送报告等场景。

    Args:
        message: 描述需要确认的操作及其影响
    """
    if not message or not message.strip():
        return "Error: message 不能为空"

    m = message.strip()
    global _pending_question
    _pending_question = {"question": m, "options": None, "type": "confirmation"}

    lines = [
        "—— 操作确认 ——",
        f"即将执行: {m}",
        "请回复「确认」继续，或「取消」放弃。",
    ]
    return "\n".join(lines)


USER_INTERACTION_TOOLS = [ask_user, request_confirmation]
