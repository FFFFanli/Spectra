"""
定时任务工具：create_cron_job / list_cron_jobs / get_cron_job /
delete_cron_job / toggle_cron_job。

允许 Agent 创建、管理定时自动化任务（如定期生成报告、巡检数据）。
参考 LobeChat Cron 工具的 API 设计。
"""

import uuid
from typing import Optional
from langchain_core.tools import tool
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from backend.state_store import (
    save_cron_job as db_save_cron_job,
    list_cron_jobs as db_list_cron_jobs,
    get_cron_job as db_get_cron_job,
    update_cron_job_status as db_update_cron_job_status,
    delete_cron_job as db_delete_cron_job,
)

_scheduler: Optional[AsyncIOScheduler] = None


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def _run_cron_task(prompt: str):
    """定时任务执行体：调用 Solo Agent 执行 prompt 并保存结果到 alerts。"""
    import asyncio
    import re as _re
    from backend.agent.single_agent import build_single_agent_graph
    from backend.tools import ALL_TOOLS as AGENT_TOOLS
    from backend.request_context import begin_request
    from backend.agent.prompts import CHART_PROMPT, SANDBOX_SYSTEM_PROMPT
    from backend.state_store import add_alert
    from langchain_core.messages import HumanMessage

    async def _run():
        begin_request("")
        tid = uuid.uuid4().hex
        system_prompt = (
            SANDBOX_SYSTEM_PROMPT
            + "\n\n你是一个智能助手，可以使用联网搜索和网页爬取工具来获取最新信息。"
            + CHART_PROMPT
        )
        graph = build_single_agent_graph(
            tools=AGENT_TOOLS,
            system_prompt=system_prompt,
            max_steps=40,
        )
        final_reply = ""
        chart_paths: list[str] = []
        async for event in graph.astream_events(
            {"messages": [HumanMessage(content=prompt)], "system_prompt": system_prompt},
            config={"configurable": {"thread_id": tid}, "recursion_limit": 100},
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    final_reply += str(chunk.content)
            elif event["event"] == "on_tool_end":
                raw = event["data"].get("output", "")
                if hasattr(raw, "content"):
                    raw = str(raw.content or "")
                else:
                    raw = str(raw)
                for marker in ("CHART_GENERATED:", "CHART_PNG_GENERATED:"):
                    for m in _re.findall(rf"{_re.escape(marker)}([^\r\n]+)", raw):
                        chart_paths.append(f"/files/{m.strip().lstrip('/')}")

        report = final_reply or "定时任务已完成，未生成具体报告文本。"
        add_alert(
            alert_id=str(uuid.uuid4()),
            prompt=prompt,
            report=report,
            charts=chart_paths,
        )
        print(f"[Cron] 任务执行成功: {prompt[:80]}...")

    try:
        asyncio.run(_run())
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            from backend.state_store import add_alert
            add_alert(
                alert_id=str(uuid.uuid4()),
                prompt=prompt,
                report=f"定时任务执行失败: {str(e)}",
                charts=[],
            )
        except Exception:
            pass


@tool
def create_cron_job(cron_expr: str, prompt: str, description: str = "") -> str:
    """创建一个定时自动化任务。任务将按 cron 表达式定期执行，结果保存到报告列表。

    Args:
        cron_expr: 标准 5 字段 cron 表达式（分 时 日 月 周）。
                   示例: "0 9 * * 1" = 每周一早上 9:00
                         "0 */6 * * *" = 每 6 小时
                         "30 8 1 * *" = 每月 1 号早上 8:30
        prompt: 每次执行时要运行的提示词/任务描述
        description: 可选的任务说明（用于列表展示）
    """
    cron_expr = cron_expr.strip()
    if not cron_expr:
        return "Error: cron_expr 不能为空"
    if not prompt or not prompt.strip():
        return "Error: prompt 不能为空"

    # 验证 cron 表达式
    try:
        CronTrigger.from_crontab(cron_expr)
    except Exception as e:
        return f"Error: cron 表达式无效 — {e}"

    job_id = f"cron_{uuid.uuid4().hex[:8]}"
    full_prompt = prompt.strip()
    if description:
        full_prompt = f"[{description}] {full_prompt}"

    # 持久化到数据库
    db_save_cron_job(job_id, cron_expr, full_prompt)

    # 注册到运行时调度器
    sched = get_scheduler()
    if sched:
        try:
            trigger = CronTrigger.from_crontab(cron_expr)
            sched.add_job(_run_cron_task, trigger, args=[full_prompt], id=job_id)
        except Exception as e:
            return f"Error: 无法注册定时任务 — {e}"

    next_info = ""
    if sched:
        job = sched.get_job(job_id)
        if job and job.next_run_time:
            next_info = f"，下次执行: {job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}"

    return (
        f"定时任务已创建 (ID: {job_id})。\n"
        f"Cron: {cron_expr}\n"
        f"任务: {full_prompt[:100]}{next_info}"
    )


@tool
def list_cron_jobs(status_filter: str = "all") -> str:
    """列出所有定时任务。

    Args:
        status_filter: "all" / "active" / "paused"
    """
    jobs = db_list_cron_jobs(status_filter)
    if not jobs:
        return "当前没有定时任务。"

    sched = get_scheduler()
    lines = [f"定时任务列表（{len(jobs)} 个）:"]
    for j in jobs:
        status_icon = "▶" if j["status"] == "active" else "⏸"
        next_run = ""
        if sched:
            sj = sched.get_job(j["job_id"])
            if sj and sj.next_run_time:
                next_run = f" → 下次: {sj.next_run_time.strftime('%m-%d %H:%M')}"
        lines.append(
            f"  {status_icon} {j['job_id']}: {j['cron_expr']} — "
            f"{j['prompt'][:60]}{next_run}"
        )
    return "\n".join(lines)


@tool
def get_cron_job_detail(job_id: str) -> str:
    """查看某个定时任务的详细信息。

    Args:
        job_id: 任务 ID
    """
    job = db_get_cron_job(job_id)
    if not job:
        return f"未找到定时任务 {job_id}。"

    sched = get_scheduler()
    next_run = ""
    if sched:
        sj = sched.get_job(job_id)
        if sj and sj.next_run_time:
            next_run = f"\n下次执行: {sj.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}"

    return (
        f"定时任务: {job['job_id']}\n"
        f"Cron: {job['cron_expr']}\n"
        f"状态: {job['status']}\n"
        f"任务: {job['prompt']}"
        f"{next_run}"
    )


@tool
def delete_cron_job(job_id: str) -> str:
    """删除一个定时任务。

    Args:
        job_id: 任务 ID
    """
    job = db_get_cron_job(job_id)
    if not job:
        return f"未找到定时任务 {job_id}。"

    # 从运行时调度器移除
    sched = get_scheduler()
    if sched:
        try:
            sched.remove_job(job_id)
        except Exception:
            pass

    delete_cron_job(job_id)
    return f"已删除定时任务 {job_id}（{job['prompt'][:60]}...）"


@tool
def toggle_cron_job(job_id: str) -> str:
    """暂停/恢复一个定时任务。

    Args:
        job_id: 任务 ID
    """
    job = db_get_cron_job(job_id)
    if not job:
        return f"未找到定时任务 {job_id}。"

    sched = get_scheduler()
    new_status = "paused" if job["status"] == "active" else "active"

    if sched:
        try:
            if new_status == "paused":
                sched.pause_job(job_id)
            else:
                sched.resume_job(job_id)
        except Exception as e:
            return f"Error: 无法切换任务状态 — {e}"

    update_cron_job_status(job_id, new_status)
    action = "已暂停" if new_status == "paused" else "已恢复"
    return f"{action}定时任务 {job_id}（{job['prompt'][:60]}...）"


CRON_TOOLS = [
    create_cron_job,
    list_cron_jobs,
    get_cron_job_detail,
    delete_cron_job,
    toggle_cron_job,
]
