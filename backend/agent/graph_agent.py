"""
图 Agent 模式 —— 动态构建多节点 DAG，每个节点是独立 Subgraph

核心理念:
  - 根据 JSON 配置动态构建 StateGraph
  - 每个 Agent 节点封装为完整的 SingleAgentGraph (自带 LLM ↔ Tool 循环)
  - 节点输出自动向下游传递
  - 支持固定流程 (如: search → analyze → report) 和条件分支

使用场景:
  - 自动化任务模板 (每日新闻 → 分析 → 报告)
  - 多步研究流水线 (竞品搜索 → 舆情分析 → 洞察报告)
  - 数据管道 (采集 → 清洗 → 建模 → 可视化)
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph import StateGraph, END, START
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, BaseMessage
from langgraph.graph.message import add_messages
from backend.checkpoint_store import get_checkpointer

from backend.agent.single_agent import build_single_agent_graph, SingleAgentState
from backend.agent.prompts import CHART_PROMPT
from backend.tools.web_search import ALL_TOOLS as DEFAULT_SEARCH_TOOLS


class WorkflowNodeConfig(TypedDict, total=False):
    """单个工作流节点配置"""
    id: str
    name: str
    system_prompt: str
    tools: list[str]          # 工具名称列表: ["web_search", "crawl_page"]
    output_key: str           # 输出结果存放的 key
    input_from: Optional[str]  # 从哪个上游节点获取输入


class WorkflowEdgeConfig(TypedDict):
    """工作流边配置"""
    from_node: str
    to_node: str
    condition: Optional[str]  # 条件表达式 (暂未使用，预留)


class WorkflowConfig(TypedDict, total=False):
    """完整工作流配置"""
    name: str
    description: str
    nodes: list[WorkflowNodeConfig]
    edges: list[WorkflowEdgeConfig]
    entry_node: str
    end_node: str


class GraphAgentState(TypedDict, total=False):
    """图 Agent 全局状态"""
    messages: Annotated[list, add_messages]
    node_outputs: dict         # {node_id: output_text}
    current_node: str
    task_goal: str
    workflow_config: dict


def _tool_name_to_tool(name: str):
    """将工具名称字符串映射为实际的 LangChain Tool"""
    tool_map = {
        "web_search": DEFAULT_SEARCH_TOOLS[0],
        "crawl_page": DEFAULT_SEARCH_TOOLS[1],
        "search_and_crawl": DEFAULT_SEARCH_TOOLS[2],
    }
    return tool_map.get(name)


def _resolve_tools(tool_names: list[str]) -> list:
    """解析工具名称列表为 LangChain Tool 实例列表"""
    tools = []
    for name in tool_names:
        t = _tool_name_to_tool(name)
        if t:
            tools.append(t)
    return tools or DEFAULT_SEARCH_TOOLS


def _build_node_subgraph(config: WorkflowNodeConfig, global_state: GraphAgentState) -> callable:
    """
    构建一个图 Agent 节点的异步执行函数。
    每个节点内部创建一个 SingleAgentGraph 子图，传递上下文后执行。
    """
    node_id = config["id"]
    node_name = config.get("name", node_id)
    system_prompt = config.get("system_prompt", "你是一个智能助手，请根据上下文完成任务。")
    tool_names = config.get("tools", ["web_search", "crawl_page"])
    tools = _resolve_tools(tool_names)
    output_key = config.get("output_key", node_id)

    async def node_fn(state: GraphAgentState) -> dict:
        node_outputs = dict(state.get("node_outputs", {}) or {})

        # 构建上游上下文
        upstream_context = ""
        for nid, output_text in node_outputs.items():
            upstream_context += f"\n\n【上游节点 {nid} 的输出】:\n{output_text[:3000]}"

        # 构建任务消息
        task_goal = state.get("task_goal", "")
        user_message = f"任务目标: {task_goal}\n\n{upstream_context}\n\n请基于以上上下文执行你的任务。"

        # 增强 system prompt（注入图表能力）
        full_system_prompt = f"{system_prompt}\n\n你的节点名称: {node_name}。完成后直接输出结果。\n\n{CHART_PROMPT}"

        subgraph = build_single_agent_graph(
            tools=tools,
            system_prompt=full_system_prompt,
            max_steps=10,
        )

        sub_messages = [HumanMessage(content=user_message)]
        try:
            result = await subgraph.ainvoke(
                {"messages": sub_messages, "system_prompt": full_system_prompt},
                config={"configurable": {"thread_id": f"graph_{node_id}"}},
            )
        except Exception as e:
            result = {"messages": [AIMessage(content=f"[节点 {node_name} 执行失败: {str(e)}]")]}

        # 提取最后一条 AI 消息作为输出
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage)]
        output_text = ai_messages[-1].content if ai_messages else f"[节点 {node_name} 无输出]"

        node_outputs[output_key] = output_text

        return {
            "node_outputs": node_outputs,
            "current_node": node_id,
            "messages": [AIMessage(content=f"**【{node_name}】**\n\n{output_text[:8000]}")],
        }

    return node_fn


def build_graph_agent(workflow_config: WorkflowConfig) -> StateGraph:
    """
    根据工作流配置动态构建 LangGraph StateGraph。

    workflow_config 示例:
    {
        "name": "每日AI新闻抓取分析",
        "description": "搜索最新AI新闻 → 分析趋势 → 生成报告",
        "nodes": [
            {"id": "search", "name": "新闻搜索",
             "system_prompt": "你是新闻搜索助手,负责搜索最新行业动态并总结。",
             "tools": ["web_search", "search_and_crawl"], "output_key": "search_results"},
            {"id": "analyze", "name": "趋势分析",
             "system_prompt": "你是行业分析专家,根据搜索材料分析关键趋势和洞察。",
             "tools": ["web_search"], "output_key": "analysis"},
            {"id": "report", "name": "报告生成",
             "system_prompt": "你是报告撰写专家,将分析结果整理成结构化报告。",
             "tools": [], "output_key": "final_report"}
        ],
        "edges": [
            {"from_node": "search", "to_node": "analyze"},
            {"from_node": "analyze", "to_node": "report"}
        ],
        "entry_node": "search",
        "end_node": "report"
    }
    """
    builder = StateGraph(GraphAgentState)
    nodes_config = workflow_config.get("nodes", [])
    edges_config = workflow_config.get("edges", [])
    entry_node = workflow_config.get("entry_node", nodes_config[0]["id"] if nodes_config else "")
    end_node_id = workflow_config.get("end_node", nodes_config[-1]["id"] if nodes_config else "")

    node_map: dict[str, str] = {}

    for node_cfg in nodes_config:
        node_id = node_cfg["id"]
        fn = _build_node_subgraph(node_cfg, {})
        builder.add_node(node_id, fn)
        node_map[node_id] = node_cfg.get("name", node_id)

    if entry_node:
        builder.add_edge(START, entry_node)

    for edge_cfg in edges_config:
        from_id = edge_cfg["from_node"]
        to_id = edge_cfg["to_node"]
        if to_id == end_node_id:
            builder.add_edge(from_id, END)
        else:
            builder.add_edge(from_id, to_id)

    # 如果 end_node 没有连接任何出边,自动连到 END
    if end_node_id:
        has_outgoing = any(e["from_node"] == end_node_id for e in edges_config)
        if not has_outgoing:
            builder.add_edge(end_node_id, END)

    return builder.compile(checkpointer=get_checkpointer())


# --- 预定义工作流模板 ---

PREDEFINED_WORKFLOWS: dict[str, WorkflowConfig] = {
    "ai_news_daily": {
        "name": "每日 AI 新闻抓取与趋势分析",
        "description": "搜索最新AI行业动态 → 智能分析关键趋势 → 生成结构化分析简报",
        "nodes": [
            {
                "id": "search",
                "name": "AI 新闻搜索",
                "system_prompt": (
                    "你是专业的科技新闻搜索助手。请使用搜索工具查找今日 AI（人工智能）领域的 "
                    "最新新闻和重要动态。涵盖以下方面：大模型发布、AI政策法规、行业融资、"
                    "技术突破、产品发布。搜索后请用中文总结 5-8 条最重要的新闻，每条包含"
                    "标题、来源和核心要点。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "search_results",
            },
            {
                "id": "analyze",
                "name": "趋势洞察分析",
                "system_prompt": (
                    "你是资深的 AI 行业分析师。请基于上游提供的新闻材料，提炼出 3-5 个"
                    "关键趋势或洞察。分析应涵盖：技术演进方向、市场竞争格局变化、"
                    "监管政策影响、投资热点。每个洞察需包含一句话总结和简要论证。"
                ),
                "tools": ["web_search"],
                "output_key": "analysis",
            },
            {
                "id": "report",
                "name": "简报生成",
                "system_prompt": (
                    "你是专业的商业报告撰写专家。请将上游的新闻摘要和趋势分析整合为一份"
                    "结构清晰、可直接发送的 AI 行业日报。格式要求：\n"
                    "1. 标题：今日 AI 要闻简报 (含日期)\n"
                    "2. 核心新闻 (列表形式)\n"
                    "3. 趋势洞察\n"
                    "4. 今日看点 (一句话总结)\n"
                    "语言精炼专业，适合发送给管理层阅读。"
                ),
                "tools": [],
                "output_key": "final_report",
            },
        ],
        "edges": [
            {"from_node": "search", "to_node": "analyze"},
            {"from_node": "analyze", "to_node": "report"},
        ],
        "entry_node": "search",
        "end_node": "report",
    },
    "competitor_monitor": {
        "name": "竞品数据监控日报",
        "description": "搜索竞品最新动态 → 产品更新分析 → 生成竞品监控报告",
        "nodes": [
            {
                "id": "search",
                "name": "竞品信息搜索",
                "system_prompt": (
                    "你是竞品情报分析专家。请使用搜索工具查找指定竞品公司的最新动态，"
                    "包括：产品更新、定价变化、市场营销活动、用户口碑变化、融资/并购新闻。"
                    "请尽量搜索多个信息源，覆盖官方网站、新闻媒体和社交媒体讨论。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "search_results",
            },
            {
                "id": "analyze",
                "name": "竞品分析",
                "system_prompt": (
                    "你是竞争战略分析师。请基于上游竞品情报，分析：\n"
                    "1. 竞品最新产品/功能变化及对我方的影响\n"
                    "2. 定价和市场策略变化\n"
                    "3. 用户舆情和口碑趋势\n"
                    "4. 风险点和机会点\n"
                    "每个维度输出 2-3 条具体分析。"
                ),
                "tools": ["web_search"],
                "output_key": "analysis",
            },
            {
                "id": "report",
                "name": "监控报告",
                "system_prompt": (
                    "你是专业商业分析师。请将竞品分析结果整合为一份竞品监控日报，"
                    "包含：标题、核心发现、详细分析、行动建议。格式清晰，适合产品/运营团队阅读。"
                ),
                "tools": [],
                "output_key": "final_report",
            },
        ],
        "edges": [
            {"from_node": "search", "to_node": "analyze"},
            {"from_node": "analyze", "to_node": "report"},
        ],
        "entry_node": "search",
        "end_node": "report",
    },
    "weekly_competitor_scan": {
        "name": "每周竞品动态巡检",
        "description": "多维度竞品搜索 → 产品/舆情/市场分析 → 综合巡检周报",
        "nodes": [
            {
                "id": "product_search",
                "name": "产品更新搜索",
                "system_prompt": (
                    "搜索竞品近期的产品更新和功能发布动态，包括官网公告、产品博客、"
                    "应用商店更新日志。重点关注新功能、UX 改进和技术架构变更。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "product_updates",
            },
            {
                "id": "sentiment_search",
                "name": "用户舆情搜索",
                "system_prompt": (
                    "搜索竞品在各平台的用户评价和讨论，包括社交媒体、产品社区、"
                    "应用商店评论。重点关注用户投诉、好评亮点和口碑变化趋势。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "sentiment",
            },
            {
                "id": "synthesize",
                "name": "综合分析",
                "system_prompt": (
                    "你是竞争战略分析师。请综合产品更新和用户舆情两方面信息，"
                    "输出一份结构化竞品巡检报告：\n"
                    "1. 产品更新摘要\n"
                    "2. 用户舆情摘要\n"
                    "3. 交叉分析 (产品变化与用户反应的关联)\n"
                    "4. 我方应对建议"
                ),
                "tools": [],
                "output_key": "final_report",
            },
        ],
        "edges": [
            {"from_node": "product_search", "to_node": "synthesize"},
            {"from_node": "sentiment_search", "to_node": "synthesize"},
        ],
        "entry_node": "product_search",
        "end_node": "synthesize",
    },
    "stock_alert": {
        "name": "股价/大盘异常监控",
        "description": "搜索实时行情 → 异常检测 → 生成告警报告",
        "nodes": [
            {
                "id": "market_search",
                "name": "市场行情搜索",
                "system_prompt": (
                    "搜索指定股票或大盘指数的今日行情数据，包括：当前价格、涨跌幅、"
                    "成交量、市值、重大公告。如有历史数据对比更好。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "market_data",
            },
            {
                "id": "alert_analysis",
                "name": "异常检测与告警",
                "system_prompt": (
                    "分析市场数据，判断是否存在异常：\n"
                    "1. 涨跌幅超过阈值 (±5%)\n"
                    "2. 成交量异常放大\n"
                    "3. 重大新闻/公告影响\n"
                    "4. 技术指标异常\n"
                    "输出简洁的告警结论和风险提示。"
                ),
                "tools": [],
                "output_key": "final_report",
            },
        ],
        "edges": [
            {"from_node": "market_search", "to_node": "alert_analysis"},
        ],
        "entry_node": "market_search",
        "end_node": "alert_analysis",
    },
    "security_vuln_daily": {
        "name": "安全漏洞日报",
        "description": "搜索最新漏洞信息 → 风险评估 → 生成漏洞日报",
        "nodes": [
            {
                "id": "vuln_search",
                "name": "漏洞信息搜索",
                "system_prompt": (
                    "搜索最新披露的安全漏洞信息 (CVE)，重点关注：高危和严重级别漏洞、"
                    "广泛使用的组件/框架漏洞、0day 漏洞、勒索软件相关漏洞。"
                ),
                "tools": ["web_search", "search_and_crawl"],
                "output_key": "vuln_data",
            },
            {
                "id": "risk_assess",
                "name": "风险评估",
                "system_prompt": (
                    "评估上游漏洞数据对企业的风险：\n"
                    "1. 漏洞严重性和利用难度\n"
                    "2. 影响范围 (是否涉及我方使用的技术栈)\n"
                    "3. 是否有可用补丁\n"
                    "4. 紧急程度和修复建议"
                ),
                "tools": [],
                "output_key": "final_report",
            },
        ],
        "edges": [
            {"from_node": "vuln_search", "to_node": "risk_assess"},
        ],
        "entry_node": "vuln_search",
        "end_node": "risk_assess",
    },
}
