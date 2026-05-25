"""
Researcher 的搜索预获取与 fallback 逻辑。

复用 legacy 的搜索 + 爬取实现，在 LLM 执行前预先获取搜索结果，
固化为 Python 字面量注入到 prompt 中。防止 LLM 直接手写 HTTP/HTML 解析。
"""

from __future__ import annotations

import json

from backend.search_service import search_and_crawl


def _build_search_data_snippet(query: str, max_results: int = 10) -> tuple[str, int, int]:
    """预获取搜索结果，返回 (snippet, sr_count, crawled_count)。

    snippet 是可直接注入 prompt 的 Python 代码片段。
    """
    results = search_and_crawl(query, max_results=max_results)
    sr_count = len(results)
    crawled_count = sum(1 for r in results if r.get("content"))

    # 构建 Python 字面量
    search_data = []
    for r in results:
        search_data.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("snippet", ""),
            "content": r.get("content", ""),
        })

    snippet = (
        "_SEARCH_RESULTS = " + json.dumps(search_data, ensure_ascii=False, indent=2) + "\n\n"
        "_CRAWLED_RESULTS = [r for r in _SEARCH_RESULTS if r.get('content')]\n\n"
        "# 请将以上数据通过 DuckDB 入库并输出分析报告。\n"
        "# 禁止 import search_service / 调用 search() / urllib / BeautifulSoup。\n"
    )
    return snippet, sr_count, crawled_count


def _build_researcher_fallback_code(search_data_snippet: str) -> str:
    """生成 researcher 的安全 fallback 代码模板。"""
    return f'''"""
Researcher 安全 fallback 模板 —— 直接使用预获取数据，不做任何 HTTP 调用。
"""
import duckdb
import pandas as pd

# 预获取的搜索数据
{search_data_snippet}

# 连接 DuckDB
con = duckdb.connect("data.duckdb")

# 将搜索结果入库
df = pd.DataFrame(_SEARCH_RESULTS)
con.execute("DROP TABLE IF EXISTS search_results")
con.execute("CREATE TABLE search_results AS SELECT * FROM df")

print(f"已入库 {{len(df)}} 条搜索结果")

# 输出摘要报告
for i, r in enumerate(_SEARCH_RESULTS[:5], 1):
    title = r.get("title", "无标题")
    url = r.get("url", "")
    snippet = r.get("snippet", "")[:200]
    content = r.get("content", "")[:500] if r.get("content") else "（未爬取全文）"
    print(f"\\n{{i}}. {{title}}\\n   URL: {{url}}\\n   摘要: {{snippet}}\\n   全文片段: {{content}}")

if len(_SEARCH_RESULTS) > 5:
    print(f"\\n... 还有 {{len(_SEARCH_RESULTS) - 5}} 条结果已入库。")

con.close()
print("\\n搜索分析完成。")
'''


def _researcher_code_needs_fallback(code: str) -> bool:
    """检查 LLM 生成的代码是否仍包含违禁 import/调用，需要 fallback。"""
    if not code:
        return True
    forbidden = [
        "from search_service", "import search_service",
        "urllib.request", "urllib.request.urlopen",
        "HTMLParser", "BeautifulSoup",
        "search_and_crawl",
    ]
    return any(f in code for f in forbidden)
