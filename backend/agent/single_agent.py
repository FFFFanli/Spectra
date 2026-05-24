"""
单 Agent 模式 —— 用 LangGraph 实现 LLM ↔ Tool 自主循环

对齐 LobeHub 的 GeneralChatAgent：
  1. AgentState 包含 messages + phase + step_count
  2. condition edge 相当于 Agent.runner() 的决策逻辑
  3. Node 相当于 AgentRuntime 的 Executor
  4. LangGraph compile() 替代了手动 step() 循环

流程: call_llm → (有 tool_calls?) → call_tools → call_llm → ... → finish

【步数到顶时的兜底】
  如果工具循环跑到接近 max_steps 上限时 LLM 还在不停调工具，
  会强制路由到 force_summarize 节点：去掉 bind_tools，让 LLM 用一段
  "请基于已收集信息直接给最终答案"的引导生成正文，避免用户看到空白消息。
"""

import asyncio
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from backend.checkpoint_store import get_checkpointer
from backend.agent.v2.llm import _create_llm


# 流式中断后重试的异常类型集合（含 httpx / anyio / openai 的中断错误）
_STREAM_CUT_ERROR_NAMES = {
    "RemoteProtocolError",       # httpx
    "ReadError",                 # httpx
    "ReadTimeout",               # httpx
    "ConnectError",              # httpx / anyio
    "APIConnectionError",        # openai SDK
    "APITimeoutError",           # openai SDK
}


def _is_stream_cut_error(exc: BaseException) -> bool:
    """判断异常是否是上游流式中断（适合重试一次）。"""
    name = type(exc).__name__
    if name in _STREAM_CUT_ERROR_NAMES:
        return True
    msg = str(exc).lower()
    keywords = (
        "incomplete chunked read",
        "peer closed connection",
        "without sending complete message body",
        "connection reset",
        "stream",
    )
    return any(k in msg for k in keywords)


def _fix_orphan_tool_calls(messages: list) -> list:
    """修复不完整的 tool_call 序列（参考 LobeChat ToolMessageReorder 处理器）。

    扫描所有消息，对每条带 tool_calls 的 AIMessage，确保后面紧跟对应的
    ToolMessage。缺失的补一条 synthetic failure message。

    这解决了 DeepSeek 400 "An assistant message with 'tool_calls' must be
    followed by tool messages responding to each 'tool_call_id'" 的问题。
    """
    if not messages:
        return messages

    # 收集所有已有的 ToolMessage 的 tool_call_id
    existing_tool_ids: set[str] = set()
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                existing_tool_ids.add(tc_id)

    # 重建消息列表：每条 AIMessage with tool_calls 后面必须跟对应的 ToolMessage
    fixed: list = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            # ToolMessage 会在对应的 AIMessage 后面被插入，这里跳过原始位置
            continue
        fixed.append(msg)
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tc_id = tc.get("id") or "unknown"
                if tc_id in existing_tool_ids:
                    # 找到原始的 ToolMessage 放回来
                    for orig in messages:
                        if isinstance(orig, ToolMessage) and getattr(orig, "tool_call_id", None) == tc_id:
                            fixed.append(orig)
                            break
                else:
                    # 补一条假的（跟 LobeChat 一样）
                    fixed.append(ToolMessage(
                        content='{"error":"Tool call was interrupted","success":false,"synthetic":true}',
                        tool_call_id=tc_id,
                    ))

    return fixed


class SingleAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    phase: str
    step_count: int
    system_prompt: str
    tools: list
    task_plan_active: bool      # create_tasks 是否已调用
    task_plan_force_count: int  # 强制 create_tasks 的重试次数
    task_plan_finished: bool    # finish_task_plan 是否已调用


class SingleAgentNodes:
    def __init__(self, tools: list):
        self.llm = _create_llm(temperature=0.7).bind_tools(tools)
        # 不绑工具的 LLM 实例，用于 force_summarize 节点
        self.llm_no_tools = _create_llm(temperature=0.7)
        self.tool_node = ToolNode(tools)

    async def call_llm(self, state: SingleAgentState) -> dict:
        messages = list(state["messages"])

        if state.get("system_prompt") and not any(
            isinstance(m, SystemMessage) for m in messages
        ):
            messages = [SystemMessage(content=state["system_prompt"])] + messages

        step = state.get("step_count", 0)
        task_plan_active = state.get("task_plan_active", False)
        force_count = state.get("task_plan_force_count", 0)

        # 如果 LLM 还没调 create_tasks，强制补指令（前 3 步持续尝试）
        if not task_plan_active and force_count < 3:
            user_msg = messages[-1].content if messages else ""
            if isinstance(user_msg, str) and len(user_msg) > 5:
                force_count += 1
                messages.append(HumanMessage(content=(
                    "【系统指令】在回答用户之前，请先调用 create_tasks 工具，"
                    "把任务拆成清晰的任务列表（JSON 数组格式的 tasks_json 参数）。"
                    "即使是简单任务，也至少要建一个任务。这是强制要求。"
                )))

        # 修复不完整的 tool_call 序列
        messages = _fix_orphan_tool_calls(messages)

        last_exc: BaseException | None = None
        for attempt in range(2):
            try:
                response = await self.llm.ainvoke(messages)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and _is_stream_cut_error(exc):
                    print(
                        f"[single_agent] LLM 流式中断（{type(exc).__name__}: {exc}），"
                        f"重试一次..."
                    )
                    await asyncio.sleep(1.5)
                    continue
                raise
        if last_exc is not None:
            raise last_exc

        return {
            "messages": [response],
            "phase": "llm_result",
            "step_count": step + 1,
            "task_plan_force_count": force_count,
        }

    async def call_tools(self, state: SingleAgentState) -> dict:
        # 在工具执行前，检查 LLM 调用了哪些工具
        task_plan_active = state.get("task_plan_active", False)
        task_plan_finished = state.get("task_plan_finished", False)

        last_msg = state["messages"][-1] if state["messages"] else None
        if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
            for tc in last_msg.tool_calls:
                name = tc.get("name", "")
                if name == "create_tasks":
                    task_plan_active = True
                elif name == "finish_task_plan":
                    task_plan_finished = True

        result = await self.tool_node.ainvoke(state["messages"])

        return {
            "messages": result,
            "phase": "tool_result",
            "task_plan_active": task_plan_active,
            "task_plan_finished": task_plan_finished,
        }

    async def force_summarize(self, state: SingleAgentState) -> dict:
        """步数到顶时的兜底节点：不绑工具，强制 LLM 基于已有信息输出最终答案。"""
        messages = list(state["messages"])

        if state.get("system_prompt") and not any(
            isinstance(m, SystemMessage) for m in messages
        ):
            messages = [SystemMessage(content=state["system_prompt"])] + messages

        # 追加一条引导消息，告诉 LLM 不要再调工具了
        messages.append(HumanMessage(content=(
            "【系统提示】你已经收集了足够的信息。请不要再调用任何工具，"
            "直接基于上面已获取的搜索结果和数据，给出完整、有条理的最终回答。"
            "如果用户要求了图表，请用 <agentArtifact> 标签内联 ECharts JSON。"
            "如果用户要求了导出文件，请调用 execute_python 生成。"
        )))

        last_exc: BaseException | None = None
        for attempt in range(2):
            try:
                response = await self.llm_no_tools.ainvoke(messages)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt == 0 and _is_stream_cut_error(exc):
                    await asyncio.sleep(1.5)
                    continue
                raise
        if last_exc is not None:
            raise last_exc

        return {
            "messages": [response],
            "phase": "summarized",
            "step_count": state.get("step_count", 0) + 1,
        }


class SingleAgentRouter:
    def __init__(self, max_steps: int = 20):
        self.max_steps = max_steps

    def after_llm(self, state: SingleAgentState) -> Literal["call_tools", "finish"]:
        # finish_task_plan 已被调用 → 直接结束
        if state.get("task_plan_finished", False):
            return "finish"
        if state.get("step_count", 0) >= self.max_steps:
            return "finish"
        last_msg = state["messages"][-1]
        if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
            return "call_tools"
        return "finish"

    def after_tools(self, state: SingleAgentState) -> Literal["call_llm", "force_summarize", "finish"]:
        # finish_task_plan 已被调用 → 直接结束
        if state.get("task_plan_finished", False):
            return "finish"
        step = state.get("step_count", 0)
        if step >= self.max_steps:
            return "force_summarize"
        # 接近上限时（还剩 2 步以内），强制总结
        if step >= self.max_steps - 2:
            return "force_summarize"
        return "call_llm"


def build_single_agent_graph(
    tools: list,
    system_prompt: str = "",
    max_steps: int = 20,
):
    nodes = SingleAgentNodes(tools)
    router = SingleAgentRouter(max_steps)

    workflow = StateGraph(SingleAgentState)

    workflow.add_node("call_llm", nodes.call_llm)
    workflow.add_node("call_tools", nodes.call_tools)
    workflow.add_node("force_summarize", nodes.force_summarize)

    workflow.set_entry_point("call_llm")

    workflow.add_conditional_edges("call_llm", router.after_llm, {
        "call_tools": "call_tools",
        "finish": END,
    })
    workflow.add_conditional_edges("call_tools", router.after_tools, {
        "call_llm": "call_llm",
        "force_summarize": "force_summarize",
        "finish": END,
    })
    # force_summarize 完成后直接结束
    workflow.add_edge("force_summarize", END)

    return workflow.compile(checkpointer=get_checkpointer())
