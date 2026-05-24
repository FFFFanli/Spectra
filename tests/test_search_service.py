import unittest
from unittest.mock import patch

import backend.search_service as search_service


class SearchServiceTests(unittest.TestCase):
    def test_build_query_variants_strips_instructional_boilerplate(self):
        variants = search_service._build_query_variants(
            "请联网搜索 2025 年 AI Agent 平台行业最新动态，并给出 5 条关键信息与来源"
        )

        self.assertIn("2025 年 AI Agent 平台行业最新动态", variants)
        self.assertEqual(len(variants), len(set(variants)))

    def test_search_falls_back_to_bing_rss_when_duckduckgo_returns_empty(self):
        expected = [
            search_service.SearchResult(
                title="AI Agent Outlook 2025",
                url="https://example.com/ai-agent-2025",
                snippet="forecast",
            )
        ]

        with patch.object(search_service, "search_duckduckgo", return_value=[]), patch.object(
            search_service, "search_bing_rss", return_value=expected
        ) as bing_mock, patch.object(search_service, "search_google", return_value=[]):
            results = search_service.search("请联网搜索 AI Agent 2025 趋势", max_results=5)

        self.assertEqual(results, expected)
        self.assertEqual(bing_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
