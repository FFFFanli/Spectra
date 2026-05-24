"""
记忆系统：用户记忆（跨会话偏好/事实） + 知识库（文档语义搜索）。

两个 ChromaDB collection：
  - "user_memory"：跨会话用户偏好、事实、经验
  - "knowledge_base"：上传文档的分块语义搜索
"""

import os
import time
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from backend.app_paths import CHROMA_DIR, ensure_directories


def _get_embeddings():
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None
    return DashScopeEmbeddings(model="text-embedding-v2", dashscope_api_key=api_key)


def _ensure_dir():
    ensure_directories()


# ── 用户记忆 collection ──

_MEMORY_COLLECTION = "user_memory"


def _get_memory_vs():
    embeddings = _get_embeddings()
    if not embeddings:
        return None
    _ensure_dir()
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name=_MEMORY_COLLECTION,
    )


def save_structured_memory(
    user_id: str,
    content: str,
    memory_type: str = "fact",
    thread_id: str = "",
    source: str = "chat",
) -> str | None:
    """保存一条结构化记忆。

    memory_type: preference | fact | experience | context
    source: chat | explicit | inferred
    返回 ChromaDB document ID。
    """
    try:
        vs = _get_memory_vs()
        if not vs:
            return None
        metadata = {
            "user_id": user_id,
            "memory_type": memory_type,
            "thread_id": thread_id,
            "timestamp": time.time(),
            "source": source,
        }
        doc = Document(page_content=content, metadata=metadata)
        ids = vs.add_documents([doc])
        doc_id = ids[0] if ids else None
        print(f"[memory] 记忆保存成功 type={memory_type} id={doc_id}")
        return doc_id
    except Exception as e:
        print(f"[memory] 保存记忆失败: {e}")
        return None


def search_user_memory(
    query: str,
    user_id: str = "default",
    memory_type: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """搜索用户记忆，支持按类型过滤。"""
    try:
        vs = _get_memory_vs()
        if not vs:
            return []
        filter_dict = {"user_id": user_id}
        if memory_type and memory_type != "all":
            filter_dict["memory_type"] = memory_type
        docs = vs.similarity_search(query, k=top_k, filter=filter_dict)
        results = []
        for d in docs:
            results.append({
                "id": getattr(d, "id", None) or "",
                "content": d.page_content,
                "memory_type": d.metadata.get("memory_type", ""),
                "thread_id": d.metadata.get("thread_id", ""),
                "timestamp": d.metadata.get("timestamp", 0),
                "source": d.metadata.get("source", ""),
            })
        return results
    except Exception as e:
        print(f"[memory] 搜索记忆失败: {e}")
        return []


def retrieve_memory_context(
    user_id: str = "default",
    query: str = "",
    top_k: int = 3,
) -> str:
    """检索与当前查询相关的记忆，返回格式化的上下文字符串。"""
    try:
        vs = _get_memory_vs()
        if not vs:
            return ""
        # 搜索所有类型
        docs = vs.similarity_search(
            query or "preferences facts",
            k=top_k,
            filter={"user_id": user_id},
        )
        if not docs:
            return ""

        # 按类型分组
        groups: dict[str, list[str]] = {}
        for d in docs:
            mt = d.metadata.get("memory_type", "other")
            groups.setdefault(mt, []).append(d.page_content)

        lines = ["[用户历史记忆]"]
        type_labels = {
            "preference": "偏好",
            "fact": "事实",
            "experience": "经验",
            "context": "上下文",
        }
        for mt, contents in groups.items():
            label = type_labels.get(mt, mt)
            for c in contents:
                lines.append(f"- [{label}] {c}")
        return "\n".join(lines)
    except Exception as e:
        print(f"[memory] 检索记忆失败: {e}")
        return ""


def get_recent_memories(user_id: str = "default", limit: int = 20) -> list[dict]:
    """获取最近记忆（按时间排序）。"""
    try:
        vs = _get_memory_vs()
        if not vs:
            return []
        # ChromaDB 不支持 order_by，用 get 获取全部后排序
        results = vs.get(where={"user_id": user_id})
        items = []
        if results and results["ids"]:
            for i, doc_id in enumerate(results["ids"]):
                items.append({
                    "id": doc_id,
                    "content": results["documents"][i] if results["documents"] else "",
                    "memory_type": results["metadatas"][i].get("memory_type", "") if results["metadatas"] else "",
                    "timestamp": results["metadatas"][i].get("timestamp", 0) if results["metadatas"] else 0,
                })
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items[:limit]
    except Exception as e:
        print(f"[memory] 获取最近记忆失败: {e}")
        return []


def delete_memory_by_query(query: str, user_id: str = "default", memory_type: str | None = None) -> int:
    """删除匹配查询的记忆（语义搜索匹配后删除）。返回删除数量。"""
    try:
        vs = _get_memory_vs()
        if not vs:
            return 0
        filter_dict: dict = {"user_id": user_id}
        if memory_type and memory_type != "all":
            filter_dict["memory_type"] = memory_type
        docs = vs.similarity_search(query, k=3, filter=filter_dict)
        if not docs:
            return 0
        ids_to_delete = [d.id for d in docs if hasattr(d, "id") and d.id]
        if ids_to_delete:
            vs.delete(ids=ids_to_delete)
        return len(ids_to_delete)
    except Exception as e:
        print(f"[memory] 删除记忆失败: {e}")
        return 0


# ── 知识库 collection ──

_KB_COLLECTION = "knowledge_base"


def _get_kb_vs():
    embeddings = _get_embeddings()
    if not embeddings:
        return None
    _ensure_dir()
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
        collection_name=_KB_COLLECTION,
    )


def add_knowledge_document(content: str, source_name: str, chunk_size: int = 500) -> int:
    """将文本内容分块并添加到知识库。返回添加的 chunk 数量。"""
    try:
        vs = _get_kb_vs()
        if not vs:
            return 0

        # 简单分块：按 chunk_size 字符切分，保持句子完整性
        chunks = _split_text(content, chunk_size)
        if not chunks:
            return 0

        now_ts = time.time()
        docs = []
        for i, chunk in enumerate(chunks):
            docs.append(Document(
                page_content=chunk,
                metadata={
                    "source": source_name,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "timestamp": now_ts,
                },
            ))

        vs.add_documents(docs)
        print(f"[kb] 知识库添加成功 source={source_name} chunks={len(docs)}")
        return len(docs)
    except Exception as e:
        print(f"[kb] 知识库添加失败: {e}")
        return 0


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """语义搜索知识库，返回带来源标注的结果。"""
    try:
        vs = _get_kb_vs()
        if not vs:
            return []
        docs = vs.similarity_search(query, k=top_k)
        results = []
        for d in docs:
            results.append({
                "content": d.page_content,
                "source": d.metadata.get("source", "未知"),
                "chunk_index": d.metadata.get("chunk_index", 0),
            })
        return results
    except Exception as e:
        print(f"[kb] 知识库搜索失败: {e}")
        return []


def list_knowledge_sources() -> list[dict]:
    """列出知识库中所有不同来源。"""
    try:
        vs = _get_kb_vs()
        if not vs:
            return []
        results = vs.get()
        if not results or not results["ids"]:
            return []

        source_counts: dict[str, int] = {}
        if results["metadatas"]:
            for m in results["metadatas"]:
                src = m.get("source", "未知")
                source_counts[src] = source_counts.get(src, 0) + 1

        return [{"source": k, "chunks": v} for k, v in source_counts.items()]
    except Exception as e:
        print(f"[kb] 列出知识库来源失败: {e}")
        return []


def remove_knowledge_source(source_name: str) -> int:
    """删除知识库中指定来源的所有 chunk。返回删除数量。"""
    try:
        vs = _get_kb_vs()
        if not vs:
            return 0
        results = vs.get(where={"source": source_name})
        if not results or not results["ids"]:
            return 0
        ids = results["ids"]
        vs.delete(ids=ids)
        print(f"[kb] 已删除知识库来源 source={source_name} count={len(ids)}")
        return len(ids)
    except Exception as e:
        print(f"[kb] 删除知识库来源失败: {e}")
        return 0


def _split_text(text: str, chunk_size: int = 500) -> list[str]:
    """简单分块：按句子边界切分，尽量保持 chunk_size 左右。"""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # 尝试向后找句子边界
            for sep in "\n。！？.!?":
                pos = text.rfind(sep, start, end)
                if pos > start + chunk_size // 2:
                    end = pos + 1
                    break
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]
