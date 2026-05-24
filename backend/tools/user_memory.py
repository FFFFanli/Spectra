"""
用户记忆工具：remember / recall / list_memories / forget。

允许 Agent 跨会话记住用户偏好、事实、经验，并在后续对话中检索。
参考 LobeChat Memory 工具的多层记忆设计。
"""

from langchain_core.tools import tool
from backend.memory import (
    save_structured_memory,
    search_user_memory,
    get_recent_memories,
    delete_memory_by_query,
)

_UID = "default"


def set_memory_user_id(user_id: str) -> None:
    global _UID
    _UID = user_id


@tool
def remember(content: str, memory_type: str = "fact") -> str:
    """【主动记住】保存一条你希望在后续对话中能回忆起来的信息。

    Args:
        content: 要记住的内容。写清楚事实/偏好是什么，不要模糊描述。
        memory_type: 记忆类型。可选:
          - "preference": 用户偏好（如"用户喜欢柱状图胜过饼图"）
          - "fact": 客观事实（如"用户公司叫Acme Corp，员工300人"）
          - "experience": 经验教训（如"上次直接用均值填充缺失值导致结果偏差"）
          - "context": 上下文（如"用户正在准备Q3投资报告"）
    """
    valid_types = {"preference", "fact", "experience", "context"}
    if memory_type not in valid_types:
        return f"Error: memory_type 必须是 {' / '.join(valid_types)} 之一"

    if not content or not content.strip():
        return "Error: content 不能为空"

    doc_id = save_structured_memory(
        user_id=_UID,
        content=content.strip(),
        memory_type=memory_type,
        source="explicit",
    )
    if doc_id:
        return f"已记住 [{memory_type}] {content[:100]}"
    return "记忆保存失败（可能 Embedding API 未配置）。"


@tool
def recall(query: str, memory_type: str = "all", top_k: int = 5) -> str:
    """【回忆】搜索用户的历史记忆。

    Args:
        query: 搜索查询，用自然语言描述你想回忆的内容
        memory_type: 过滤记忆类型。"all" 搜索全部，"preference"/"fact"/"experience"/"context" 过滤某一种
        top_k: 返回结果数量，默认 5
    """
    if not query or not query.strip():
        return "Error: query 不能为空"

    mt = None if memory_type == "all" else memory_type
    results = search_user_memory(query, user_id=_UID, memory_type=mt, top_k=top_k)
    if not results:
        return f"未找到与 '{query}' 相关的记忆。"

    lines = [f"回忆起 {len(results)} 条相关记忆："]
    type_labels = {"preference": "偏好", "fact": "事实", "experience": "经验", "context": "上下文"}
    for i, r in enumerate(results):
        label = type_labels.get(r["memory_type"], r["memory_type"])
        lines.append(f"\n[{i + 1}] [{label}] {r['content']}")
    return "\n".join(lines)


@tool
def list_memories(memory_type: str = "all", limit: int = 10) -> str:
    """列出最近的记忆（按时间倒序）。

    Args:
        memory_type: "all" 列出所有类型，或指定 "preference"/"fact"/"experience"/"context"
        limit: 返回条数，默认 10
    """
    items = get_recent_memories(user_id=_UID, limit=limit * 3)  # 多取再过滤

    if memory_type != "all":
        items = [m for m in items if m["memory_type"] == memory_type]

    items = items[:limit]
    if not items:
        return "暂无记忆。"

    type_labels = {"preference": "偏好", "fact": "事实", "experience": "经验", "context": "上下文"}
    lines = [f"最近的 {len(items)} 条记忆："]
    for i, m in enumerate(items):
        label = type_labels.get(m["memory_type"], m["memory_type"])
        lines.append(f"{i + 1}. [{label}] {m['content'][:120]}")
    return "\n".join(lines)


@tool
def forget(query: str, memory_type: str = "all") -> str:
    """【忘记】删除匹配查询的记忆。

    Args:
        query: 搜索查询，匹配到的记忆将被删除
        memory_type: 只删除特定类型的记忆。"all" 搜索全部类型
    """
    if not query or not query.strip():
        return "Error: query 不能为空"

    mt = None if memory_type == "all" else memory_type
    count = delete_memory_by_query(query, user_id=_UID, memory_type=mt)
    if count == 0:
        return f"未找到与 '{query}' 匹配的记忆，没有删除。"
    return f"已删除 {count} 条匹配的记忆。"


USER_MEMORY_TOOLS = [remember, recall, list_memories, forget]
