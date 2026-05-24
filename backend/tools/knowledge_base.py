"""
知识库工具：list_knowledge_files / search_knowledge_base /
add_to_knowledge_base / remove_from_knowledge_base。

提供对上传文档的语义搜索、添加、删除功能。
"""

import json
from langchain_core.tools import tool
from backend.memory import (
    list_knowledge_sources,
    search_knowledge,
    add_knowledge_document,
    remove_knowledge_source,
)


@tool
def list_knowledge_files() -> str:
    """列出知识库中的所有文件/来源及其 chunk 数量。"""
    sources = list_knowledge_sources()
    if not sources:
        return "知识库为空，没有已索引的文档。"

    lines = ["知识库中的文件："]
    for s in sources:
        lines.append(f"  - {s['source']}（{s['chunks']} 个文本块）")
    return "\n".join(lines)


@tool
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """对知识库中的文档进行语义搜索。返回最相关的文本片段及其来源。

    Args:
        query: 搜索查询，使用自然语言描述你想找的内容
        top_k: 返回结果数量，默认 5
    """
    if not query or not query.strip():
        return "Error: query 不能为空"

    results = search_knowledge(query, top_k=top_k)
    if not results:
        return f"未找到与 '{query}' 相关的知识库内容。"

    lines = [f"搜索 '{query}' 的结果（共 {len(results)} 条）："]
    for i, r in enumerate(results):
        lines.append(f"\n[{i + 1}] 来源: {r['source']}（chunk {r['chunk_index']}）")
        lines.append(f"    {r['content'][:300]}")
    return "\n".join(lines)


@tool
def add_to_knowledge_base(content: str, source_name: str) -> str:
    """将文本内容添加到知识库。适合保存搜索结果、分析结论、重要文档片段等。

    Args:
        content: 要添加的文本内容
        source_name: 来源名称（如 "Q3销售报告"、"竞品分析2024"），用于后续检索时标注来源
    """
    if not content or not content.strip():
        return "Error: content 不能为空"
    if not source_name or not source_name.strip():
        return "Error: source_name 不能为空"

    count = add_knowledge_document(content.strip(), source_name.strip())
    if count == 0:
        return "知识库添加失败（可能 Embedding API 未配置）。"
    return f"已添加 '{source_name}' 到知识库（{count} 个文本块）。"


@tool
def remove_from_knowledge_base(source_name: str) -> str:
    """从知识库中删除指定来源的所有内容。

    Args:
        source_name: 要删除的来源名称
    """
    if not source_name or not source_name.strip():
        return "Error: source_name 不能为空"

    count = remove_knowledge_source(source_name.strip())
    if count == 0:
        return f"未找到来源 '{source_name}' 的内容。"
    return f"已从知识库中删除 '{source_name}'（{count} 个文本块）。"


KNOWLEDGE_BASE_TOOLS = [
    list_knowledge_files,
    search_knowledge_base,
    add_to_knowledge_base,
    remove_from_knowledge_base,
]
