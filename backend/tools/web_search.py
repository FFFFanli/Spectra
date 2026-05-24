"""
LangChain Tool 包装 —— 将 search_service 的纯函数注册为 LLM 可调用的 Tool

工具清单:
  - web_search: 联网搜索
  - crawl_page:  爬取指定网页全文
  - search_and_crawl_tool: 搜索并爬取前 N 篇全文 (组合工具)

【上下文长度策略】
为了避免长上下文叠加 thinking 模式触发上游流式中断（peer closed connection），
工具结果做严格截断：
- crawl_page: 单篇全文 ≤ 4000 字符
- search_and_crawl_tool: 每篇全文 ≤ 2500 字符
LLM 拿到截断的内容仍可基于摘要+核心段落完成总结。
"""

from langchain_core.tools import tool
from backend.search_service import search, crawl, search_and_crawl
from backend.search_service import SearchResult, CrawlResult


# 单页全文截断长度（手动调用 crawl_page 时使用）
_CRAWL_SINGLE_LIMIT = 4000
# 组合工具中每篇全文截断长度（一次调用通常爬 3 篇，整体输出更紧凑）
_CRAWL_BATCH_LIMIT = 2500


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[已截断，原文还有 {len(text) - limit} 字符]"


@tool
def web_search(query: str, max_results: int = 8) -> str:
    """
    联网搜索获取最新信息。
    当需要实时数据、新闻、事实核查时使用此工具。

    Args:
        query: 搜索关键词 (中文或英文)
        max_results: 最大返回结果数，默认 8
    """
    results: list[SearchResult] = search(query, max_results=max_results)

    if not results:
        return "No search results found. 未找到任何搜索结果，请尝试更换关键词。"

    parts = ["<search_results>"]
    for i, r in enumerate(results, 1):
        parts.append(f"  <result index=\"{i}\">")
        parts.append(f"    <title>{r.title}</title>")
        parts.append(f"    <url>{r.url}</url>")
        if r.snippet:
            parts.append(f"    <snippet>{r.snippet[:500]}</snippet>")
        parts.append(f"  </result>")
    parts.append("</search_results>")
    return "\n".join(parts)


@tool
def crawl_page(url: str) -> str:
    """
    爬取指定网页的完整内容。
    当需要阅读、分析具体网页时使用此工具。

    Args:
        url: 网页地址 (必须以 http:// 或 https:// 开头)
    """
    result: CrawlResult | None = crawl(url)

    if result and len(result.content) > 50:
        return (
            f"<crawl_result>\n"
            f"  <url>{result.url}</url>\n"
            f"  <title>{result.title}</title>\n"
            f"  <content>{_truncate(result.content, _CRAWL_SINGLE_LIMIT)}</content>\n"
            f"</crawl_result>"
        )

    return f"<crawl_error>Failed to crawl {url}. 该网页无法访问或内容过短。</crawl_error>"


@tool
def search_and_crawl_tool(query: str, max_search: int = 5, max_crawl: int = 3) -> str:
    """
    搜索并同时爬取前 N 篇结果的全文。一次性完成"搜索 + 深度阅读"。
    当用户要求"搜索并总结"时优先使用此组合工具。

    Args:
        query: 搜索关键词
        max_search: 搜索返回的最大结果数，默认 5
        max_crawl: 实际爬取的文章数，默认 3
    """
    sr_list, crawled_list = search_and_crawl(
        query, search_results=max_search, crawl_count=max_crawl
    )

    parts = []

    if sr_list:
        parts.append("<search_results>")
        for i, r in enumerate(sr_list, 1):
            parts.append(f"  <result index=\"{i}\">")
            parts.append(f"    <title>{r.title}</title>")
            parts.append(f"    <url>{r.url}</url>")
            parts.append(f"  </result>")
        parts.append("</search_results>")

    if crawled_list:
        parts.append("<crawled_articles>")
        for i, cr in enumerate(crawled_list, 1):
            parts.append(f"  <article index=\"{i}\">")
            parts.append(f"    <url>{cr.url}</url>")
            parts.append(f"    <title>{cr.title}</title>")
            parts.append(f"    <content>{_truncate(cr.content, _CRAWL_BATCH_LIMIT)}</content>")
            parts.append(f"  </article>")
        parts.append("</crawled_articles>")

    if not parts:
        return "No results found. 搜索和爬取均未获得有效结果。"

    return "\n".join(parts)


ALL_TOOLS = [web_search, crawl_page, search_and_crawl_tool]
