from __future__ import annotations

import uuid

from langchain_core.tools import tool

from backend.report_generator import generate_report


@tool
def export_conversation(format: str, title: str, content: str) -> str:
    """
    将对话内容或分析结果导出为 PDF 或 DOCX 文档文件。

    适用场景:
    - 用户要求"导出 pdf"、"导出 docx"、"整理成文档"时
    - 当分析任务已经完成，用户希望保存对话成果时
    - 需要将长篇分析结果整理为正式文档时

    参数 content 应该是你整理好的、准备写入文档的完整正文内容，
    可以包含完整的对话历史摘要、数据表格、分析结论等。
    请用清晰的结构组织内容（标题、段落、列表等）。

    Args:
        format: 导出格式，必须是 "pdf" 或 "docx"
        title: 文档标题
        content: 要写入文档的完整正文内容
    """
    if format not in ("pdf", "docx"):
        return f"不支持的导出格式: {format}，仅支持 pdf 或 docx"

    thread_id = f"export_{uuid.uuid4().hex[:8]}"

    try:
        result = generate_report(format, title, content, thread_id)
        file_path = result["file_path"]
        filename = result["filename"]
        return (
            f"EXPORT_FILE:{file_path}|{filename}|{format.upper()}\n"
            f"文档已成功导出: {filename}\n"
            f"文件路径: {file_path}"
        )
    except Exception as e:
        return f"导出失败: {str(e)}"


@tool
def generate_docx(format: str, title: str = "", content: str = "") -> str:
    """
    将本次对话最近一条 assistant 回复导出为 DOCX 或 PDF 文档。这是导出文件的首选工具，
    使用时**只需传 format 一个参数**，content 会由系统自动取最新回复正文（含图表占位符）。

    【何时使用】
    当用户说"导出 docx"、"导出 pdf"、"整理成文档"、"保存为 word"、
    "生成报告"等任何导出/生成文件的请求时，**直接调用本工具**，
    不要先调 execute_python 自己写 python-docx 代码（那条路径慢且容易丢图）。

    【调用方式（强烈推荐）】
    ```
    generate_docx(format="docx")        ← 推荐，自动取最近一条 assistant 回复
    generate_docx(format="pdf")
    ```

    系统会自动：
    1. 把最近一条 assistant 回复的 markdown 正文（**包含 <agentArtifact> 标签**）作为 content
    2. 把前端已经渲染好的 ECharts PNG 嵌到对应位置
    3. 渲染中文字体、表格、列表、加粗等格式

    【参数兜底（一般不用传）】
    - format: "docx" 或 "pdf"
    - title: 报告标题（缺省自动从 markdown H1 提取）
    - content: 报告正文 markdown（缺省自动取最近一条 assistant 回复）
      * **必须保留 <agentArtifact> 标签**，否则文档里不会出现图表
      * 一般情况下让系统自动取，**不要手动重写**

    Args:
        format: 导出格式，"pdf" 或 "docx"
        title: 文档主标题（可选）
        content: Markdown 格式的报告正文（可选，缺省自动取）
    """
    if format not in ("pdf", "docx"):
        return f"不支持的导出格式: {format}，仅支持 pdf 或 docx"

    final_title = title or ""
    final_content = content or ""
    try:
        from backend.request_context import get_export_content, get_last_assistant_reply
        # 优先取前端注入的导出内容（含完整的 <agentArtifact> 图表标签）
        injected = get_export_content() or {}
        injected_content = (injected.get("content") or "").strip()
        injected_title = (injected.get("title") or "").strip()
        if injected_content:
            final_content = injected_content
        if injected_title and not final_title:
            final_title = injected_title
        # fallback: 取上一轮 agent 回复的缓存正文
        if not final_content.strip():
            fallback_reply = get_last_assistant_reply()
            if fallback_reply.strip():
                final_content = fallback_reply.strip()
    except Exception:
        pass

    if not final_content.strip():
        return "❌ 文档生成失败: 没有可导出的正文内容。请先让 agent 生成分析报告（包含文字和图表），再导出。"

    if not final_title:
        final_title = "Spectra 分析报告"

    thread_id = f"report_{uuid.uuid4().hex[:8]}"

    # 从请求上下文获取前端附带的图表 PNG
    charts = []
    try:
        from backend.request_context import get_attached_charts
        attached = get_attached_charts()
        if attached:
            charts = [
                {
                    "chartId": f"chart_{i}",
                    "title": c.get("title") or "",
                    "dataUrl": _png_bytes_to_data_url(c.get("png_bytes")),
                }
                for i, c in enumerate(attached)
                if c.get("png_bytes")
            ]
    except Exception:
        pass

    try:
        result = generate_report(
            format_type=format,
            title=final_title,
            content=final_content,
            thread_id=thread_id,
            charts=charts,
        )
        file_path = result["file_path"]
        filename = result["filename"]
        # file_path 已经是 "/files/xxx/yyy.docx" 格式，直接用作 URL
        # FILE_GENERATED marker 后面跟的是相对于 /files/ 的路径
        rel_path = file_path.lstrip("/").removeprefix("files/")
        return (
            f"FILE_GENERATED:{rel_path}\n"
            f"✅ 文档已成功生成: {filename}\n"
            f"📥 下载路径: {file_path}"
        )
    except Exception as e:
        return f"❌ 文档生成失败: {str(e)}"


def _png_bytes_to_data_url(png_bytes: bytes | None) -> str:
    if not png_bytes:
        return ""
    import base64
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


EXPORT_TOOLS = [export_conversation, generate_docx]
