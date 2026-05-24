"""
联网搜索 + 网页爬取服务
纯 stdlib (urllib + re + html)，无需额外依赖，可在沙箱中独立运行。

搜索: DuckDuckGo HTML (无需 API Key)
爬取: Jina AI r.jina.ai (无需 API Key)
备选: Google HTML 搜索
"""

import html as _html_mod
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass
class CrawlResult:
    url: str
    title: str
    content: str
    content_type: str = "markdown"


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_QUERY_STOPWORDS = {
    "请",
    "帮我",
    "请帮我",
    "联网",
    "联网搜索",
    "上网搜",
    "搜索",
    "搜索一下",
    "查找",
    "查询",
    "给出",
    "并给出",
    "并附上",
    "来源",
    "链接",
    "最新",
    "实时",
    "关键信息",
    "信息",
    "动态",
    "一下",
}


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _normalize_query(query: str) -> str:
    normalized = query.strip()
    for phrase in ["请联网搜索", "联网搜索", "联网查询", "上网搜", "搜索一下", "请搜索", "搜索", "查找", "查询"]:
        normalized = normalized.replace(phrase, " ")
    boilerplate_patterns = [
        r"^(?:(?:请|麻烦|帮我|请帮我)\s*)+",
        r"(并|并且).{0,18}(给出|提供).{0,18}(来源|链接|信息).*$",
        r"(给出|提供).{0,12}\d+条.{0,12}(来源|链接).*$",
    ]
    for pattern in boilerplate_patterns:
        normalized = re.sub(pattern, " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[\"'“”‘’（）()\[\]{}]+", " ", normalized)
    normalized = re.sub(r"^[，,。；;：:\s]+|[，,。；;：:\s]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:120]


def _extract_keyword_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9\.\-]*|[\u4e00-\u9fff]{2,}", query)
    filtered: list[str] = []
    for token in tokens:
        compact = token.strip()
        if not compact:
            continue
        if compact.lower() in _QUERY_STOPWORDS or compact in _QUERY_STOPWORDS:
            continue
        filtered.append(compact)
    return " ".join(filtered[:10]).strip()


def _build_query_variants(query: str) -> list[str]:
    variants: list[str] = []
    for candidate in [query.strip(), _normalize_query(query), _extract_keyword_query(query)]:
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants or [query.strip()]


def _dedupe_results(results: list[SearchResult], max_results: int) -> list[SearchResult]:
    deduped: list[SearchResult] = []
    seen: set[str] = set()
    for item in results:
        key = item.url.strip().lower() or item.title.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max_results:
            break
    return deduped


def _decode_ddg_url(raw_url: str) -> str:
    """解码 DuckDuckGo 重定向链接"""
    # 处理协议相对 URL
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    if "uddg=" in raw_url:
        m = re.search(r"uddg=([^&]+)", raw_url)
        if m:
            return urllib.parse.unquote(m.group(1))
    return raw_url


def search_duckduckgo(query: str, max_results: int = 10) -> list[SearchResult]:
    """
    通过 DuckDuckGo HTML 搜索（无需 API Key）。
    分别提取链接/标题和摘要，然后按位置配对。
    """
    params = urllib.parse.urlencode({"q": query})
    url = f"https://html.duckduckgo.com/html/?{params}"
    try:
        html_text = _fetch(url, timeout=15)
    except Exception as e:
        print(f"[SearchService] DuckDuckGo 请求失败: {e}")
        return []

    results: list[SearchResult] = []

    # 提取所有 result__a 标签：链接和标题
    link_pattern = re.compile(
        r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    links = link_pattern.findall(html_text)

    # 提取所有 result__snippet 标签的内容
    snippet_pattern = re.compile(
        r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippets_raw = snippet_pattern.findall(html_text)

    for i, (url_raw, title_html) in enumerate(links):
        title = _html_mod.unescape(re.sub(r"<[^>]+>", "", title_html).strip())
        if not title:
            continue

        decoded_url = _decode_ddg_url(url_raw)
        if not decoded_url.startswith("http"):
            continue

        snippet = ""
        if i < len(snippets_raw):
            snippet = _html_mod.unescape(
                re.sub(r"<[^>]+>", "", snippets_raw[i]).strip()
            )

        results.append(SearchResult(title=title, url=decoded_url, snippet=snippet[:500]))

    return results[:max_results]


def search_google(query: str, max_results: int = 10) -> list[SearchResult]:
    """Google 网页搜索备选（无需 API Key）"""
    params = urllib.parse.urlencode({"q": query, "hl": "zh-CN"})
    url = f"https://www.google.com/search?{params}"
    try:
        html_text = _fetch(url, timeout=15)
    except Exception as e:
        print(f"[SearchService] Google 请求失败: {e}")
        return []

    results: list[SearchResult] = []

    # Google 搜索结果结构
    for block in re.findall(r'<div class="g "[^>]*>.*?</div></div></div>', html_text, re.DOTALL):
        link_m = re.search(r'href="(/url\?q=)([^"&]+)', block)
        if not link_m:
            link_m = re.search(r'href="(https?://[^"]+)"', block)

        url_decoded = ""
        if link_m:
            if link_m.group(1) == "/url?q=":
                url_decoded = urllib.parse.unquote(link_m.group(2))
            else:
                url_decoded = link_m.group(1)

        title_m = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.DOTALL)
        title = _html_mod.unescape(re.sub(r"<[^>]+>", "", title_m.group(1)).strip()) if title_m else ""

        snippet_m = re.search(
            r'<span[^>]*class="[^"]*st[^"]*"[^>]*>(.*?)</span>', block, re.DOTALL
        )
        snippet = ""
        if snippet_m:
            snippet = _html_mod.unescape(re.sub(r"<[^>]+>", "", snippet_m.group(1)).strip())[:500]

        if title and url_decoded.startswith("http"):
            results.append(SearchResult(title=title, url=url_decoded, snippet=snippet))

    return results[:max_results]


def search_bing_rss(query: str, max_results: int = 10) -> list[SearchResult]:
    """Bing RSS 搜索备选，结构比 HTML 更稳定。"""
    params = urllib.parse.urlencode({"q": query})
    url = f"https://www.bing.com/search?format=rss&{params}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        data = urllib.request.urlopen(req, timeout=15).read()
        root = ET.fromstring(data)
    except Exception as e:
        print(f"[SearchService] Bing RSS 请求失败: {e}")
        return []

    results: list[SearchResult] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = _html_mod.unescape((item.findtext("description") or "").strip())
        description = re.sub(r"<[^>]+>", "", description)
        if title and link.startswith("http"):
            results.append(SearchResult(title=title, url=link, snippet=description[:500]))
    return _dedupe_results(results, max_results)


def search(query: str, max_results: int = 10) -> list[SearchResult]:
    """多引擎 + 多查询变体 fallback 搜索"""
    providers = [
        ("DuckDuckGo", search_duckduckgo),
        ("Bing RSS", search_bing_rss),
        ("Google", search_google),
    ]
    for candidate_query in _build_query_variants(query):
        print(f"[SearchService] 尝试搜索查询: {candidate_query}")
        for provider_name, provider in providers:
            results = _dedupe_results(provider(candidate_query, max_results), max_results)
            if results:
                print(f"[SearchService] {provider_name} 命中 {len(results)} 条结果。")
                return results
            print(f"[SearchService] {provider_name} 未返回结果，继续尝试下一个来源...")
    return []


def crawl_jina(url: str) -> Optional[CrawlResult]:
    """
    通过 Jina AI 爬取网页全文，返回 Markdown 格式内容。
    完全免费，无需 API Key。
    """
    jina_url = f"https://r.jina.ai/{url}"
    try:
        text = _fetch(jina_url, timeout=30)
        if text and len(text) > 100:
            title = url
            title_match = re.search(r"(?i)Title:\s*(.+)", text)
            if title_match:
                title = title_match.group(1).strip()
            return CrawlResult(url=url, title=title, content=text, content_type="markdown")
        return None
    except Exception as e:
        print(f"[SearchService] Jina 爬取失败 ({url}): {e}")
        return None


def crawl_naive(url: str) -> Optional[CrawlResult]:
    """简单 HTTP 直连爬取，提取纯文本"""
    try:
        html_text = _fetch(url, timeout=20)
        # 提取 title
        title = url
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE)
        if title_match:
            title = _html_mod.unescape(title_match.group(1).strip())
        # 去除 script/style/nav/footer 等
        for tag in ("script", "style", "nav", "footer", "noscript", "iframe", "head"):
            html_text = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
        # 提取文本
        text = re.sub(r"<[^>]+>", " ", html_text)
        text = re.sub(r"\s+", " ", text).strip()
        # 截断
        text = text[:15000]
        return CrawlResult(url=url, title=title, content=text, content_type="text")
    except Exception as e:
        print(f"[SearchService] Naive 爬取失败 ({url}): {e}")
        return None


def crawl(url: str) -> Optional[CrawlResult]:
    """多爬虫 fallback 爬取"""
    result = crawl_jina(url)
    if not result:
        result = crawl_naive(url)
    return result


# ── 便利函数：搜索 + 爬取 top N ──

def search_and_crawl(
    query: str,
    search_results: int = 5,
    crawl_count: int = 3,
) -> tuple[list[SearchResult], list[CrawlResult]]:
    """
    搜索并爬取前 N 篇全文。
    返回 (搜索结果列表, 爬取结果列表)。
    """
    sr = search(query, max_results=search_results)
    if not sr:
        return [], []

    crawled: list[CrawlResult] = []
    for r in sr[:crawl_count]:
        print(f"[SearchService] 正在爬取: {r.url[:80]}...")
        cr = crawl(r.url)
        if cr:
            crawled.append(cr)

    return sr, crawled
