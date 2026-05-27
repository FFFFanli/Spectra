"""
PlanScheduler —— 依赖图拓扑序调度，最大并发 4。

调度算法：
  while plan has pending/running steps:
      ready = [pending steps where all dependencies are completed]
      batch = ready[:4]
      mark batch as running → emit step_started
      results = await asyncio.gather(*execute_step(s) for s in batch)
      for each result:
          if failed and retry < 3: retry
          elif failed and retry >= 3: trigger revise_plan
          else: mark completed → emit step_completed

满足：R5, R12
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from backend.agent.v2.mtc.plan_manager import Plan, PlanManager, PlanStep

# Token usage 隔离：每个并行步骤独立的 usage 上下文
_step_usage: ContextVar[Optional[dict]] = ContextVar("step_usage", default=None)


class PlanScheduler:
    MAX_CONCURRENCY = 4

    def __init__(self, plan_manager: PlanManager):
        self._plan_manager = plan_manager
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENCY)

    async def run_plan(
        self,
        execute_step_fn: Callable[[PlanStep], Awaitable[dict]],
        emit_fn: Callable[[str, dict], None],
        on_revise_needed: Callable[[str], Awaitable[None]],
    ) -> None:
        """主调度循环：取 ready 步骤 → 并行执行 → 更新状态 → 重复直到全部完成。"""
        pm = self._plan_manager

        while not pm.all_completed:
            ready = pm.get_ready_steps()
            if not ready:
                # 检查是否有 running 步骤（如果有，等待它们完成）
                running = [s for s in pm.plan.steps if s.status == "running"] if pm.plan else []
                if running:
                    await asyncio.sleep(0.5)
                    continue
                # 没有 running 也没有 ready → 可能全部完成了
                break

            batch = ready[: self.MAX_CONCURRENCY]

            # Mark as running
            for step in batch:
                pm.update_step(step.id, "running")
                emit_fn("step_started", {
                    "step_id": step.id,
                    "assignee_agent_id": step.assignee_agent_id,
                    "description": step.description,
                })

            # Execute in parallel
            tasks = []
            for step in batch:
                tasks.append(self._execute_single(step, execute_step_fn, emit_fn, on_revise_needed))

            await asyncio.gather(*tasks)

    async def _execute_single(
        self,
        step: PlanStep,
        execute_step_fn: Callable[[PlanStep], Awaitable[dict]],
        emit_fn: Callable[[str, dict], None],
        on_revise_needed: Callable[[str], Awaitable[None]],
    ) -> None:
        """执行单个步骤（含重试逻辑）。"""
        pm = self._plan_manager

        async with self._semaphore:
            # 设置隔离的 token usage 上下文
            usage_ctx = {}
            token = _step_usage.set(usage_ctx)

            try:
                result = await execute_step_fn(step)

                if result.get("status") == "ok":
                    reply_text = result.get("reply", "")
                    pm.update_step(step.id, "completed", note=reply_text)
                    if result.get("artifacts"):
                        for a in result["artifacts"]:
                            step.artifacts.append(a)
                    emit_fn("step_completed", {
                        "step_id": step.id,
                        "artifacts": step.artifacts,
                        "reply": reply_text,
                    })
                else:
                    retry_count = pm.increment_retry(step.id)
                    if pm.should_revise(step.id):
                        # retry_count >= MAX_STEP_RETRIES → 触发 revise_plan
                        pm.update_step(step.id, "failed", note=result.get("error", ""))
                        emit_fn("step_failed", {
                            "step_id": step.id,
                            "error": result.get("error", ""),
                            "retry_count": retry_count,
                        })
                        await on_revise_needed(f"step_{step.id}_max_retries")
                    else:
                        # 还有重试次数 → 重置为 pending，下一轮调度自动重试
                        pm.update_step(step.id, "pending", note=result.get("error", ""))
                        emit_fn("step_failed", {
                            "step_id": step.id,
                            "error": result.get("error", ""),
                            "retry_count": retry_count,
                        })
            except Exception as e:
                retry_count = pm.increment_retry(step.id)
                if pm.should_revise(step.id):
                    pm.update_step(step.id, "failed", note=str(e))
                    emit_fn("step_failed", {
                        "step_id": step.id,
                        "error": str(e),
                        "retry_count": retry_count,
                    })
                    await on_revise_needed(f"step_{step.id}_max_retries")
                else:
                    pm.update_step(step.id, "pending", note=str(e))
                    emit_fn("step_failed", {
                        "step_id": step.id,
                        "error": str(e),
                        "retry_count": retry_count,
                    })
            finally:
                _step_usage.reset(token)

    @staticmethod
    def get_step_usage() -> Optional[dict]:
        """获取当前步骤的 token usage 上下文。"""
        return _step_usage.get()
