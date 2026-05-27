"""
PlanManager —— Plan 生命周期管理。

负责 Plan 的创建、更新、重排、终止。
满足：R3, R12
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class PlanStep:
    id: str                    # uuid hex[:8]
    description: str
    assignee_agent_id: str     # coder|writer|researcher|responder|designer|reviewer
    status: str = "pending"    # pending|running|completed|failed|skipped
    dependencies: list[str] = field(default_factory=list)
    note: str = ""
    retry_count: int = 0
    artifacts: list[dict] = field(default_factory=list)


@dataclass
class Plan:
    plan_id: str
    thread_id: str
    steps: list[PlanStep]
    created_at: str
    updated_at: str
    revise_count: int = 0


class PlanManager:
    MAX_STEPS = 30
    MAX_STEP_RETRIES = 3
    MAX_REVISE_COUNT = 3

    def __init__(self, thread_id: str):
        self._thread_id = thread_id
        self._plan: Optional[Plan] = None

    def create_plan(self, steps_raw: list[dict]) -> Plan:
        """从 LLM 产出的原始步骤列表创建 Plan。"""
        if len(steps_raw) > self.MAX_STEPS:
            steps_raw = steps_raw[: self.MAX_STEPS]

        steps = []
        for s in steps_raw:
            step = PlanStep(
                id=uuid.uuid4().hex[:8],
                description=s.get("description", ""),
                assignee_agent_id=s.get("assignee_agent_id", "responder"),
                dependencies=s.get("dependencies", []),
            )
            steps.append(step)

        # 将依赖描述解析为 step ID（LLM 可能用描述文本或索引而非 ID）
        for step in steps:
            resolved = []
            for dep in step.dependencies:
                resolved_id = self._resolve_dependency(dep, steps)
                if resolved_id:
                    resolved.append(resolved_id)
            step.dependencies = resolved

        now = datetime.now(timezone.utc).isoformat()
        self._plan = Plan(
            plan_id=uuid.uuid4().hex[:8],
            thread_id=self._thread_id,
            steps=steps,
            created_at=now,
            updated_at=now,
        )
        return self._plan

    @staticmethod
    def _resolve_dependency(dep: str, steps: list[PlanStep]) -> str | None:
        """将依赖引用解析为 step ID。支持：ID 直匹配、描述匹配、数字索引。"""
        if not dep:
            return None
        # 1. 直接 ID 匹配
        for s in steps:
            if s.id == dep:
                return s.id
        # 2. 描述文本精确匹配
        for s in steps:
            if s.description == dep:
                return s.id
        # 3. 描述文本包含匹配（LLM 可能截断或改写）
        for s in steps:
            if dep in s.description or s.description in dep:
                return s.id
        # 4. 数字索引
        try:
            idx = int(dep)
            if 0 <= idx < len(steps):
                return steps[idx].id
        except (ValueError, TypeError):
            pass
        return None

    def update_step(self, step_id: str, status: str, note: str = "") -> PlanStep:
        """更新单个步骤的状态（含可选备注）。"""
        if not self._plan:
            raise ValueError("Plan not created yet")
        for step in self._plan.steps:
            if step.id == step_id:
                step.status = status
                if note:
                    step.note = note
                self._plan.updated_at = datetime.now(timezone.utc).isoformat()
                return step
        raise ValueError(f"Step {step_id} not found")

    def add_step(self, after_step_id: str, description: str, assignee: str) -> PlanStep:
        """在指定步骤之后插入新步骤。"""
        if not self._plan:
            raise ValueError("Plan not created yet")
        if len(self._plan.steps) >= self.MAX_STEPS:
            raise ValueError(f"Plan already has {self.MAX_STEPS} steps (max)")

        new_step = PlanStep(
            id=uuid.uuid4().hex[:8],
            description=description,
            assignee_agent_id=assignee,
        )

        insert_idx = len(self._plan.steps)
        for i, step in enumerate(self._plan.steps):
            if step.id == after_step_id:
                insert_idx = i + 1
                break

        self._plan.steps.insert(insert_idx, new_step)
        self._plan.updated_at = datetime.now(timezone.utc).isoformat()
        return new_step

    def revise_plan(self, reason: str, new_steps: list[dict]) -> Plan:
        """重排 Plan：保留已 completed 的步骤，替换其余步骤。"""
        if not self._plan:
            raise ValueError("Plan not created yet")

        completed_steps = [s for s in self._plan.steps if s.status == "completed"]

        new_step_objs = []
        for s in new_steps:
            new_step_objs.append(PlanStep(
                id=uuid.uuid4().hex[:8],
                description=s.get("description", ""),
                assignee_agent_id=s.get("assignee_agent_id", "responder"),
                dependencies=s.get("dependencies", []),
            ))

        self._plan.steps = completed_steps + new_step_objs
        self._plan.revise_count += 1
        self._plan.updated_at = datetime.now(timezone.utc).isoformat()
        return self._plan

    def finish(self, summary: str) -> Plan:
        """结束 Plan：将所有未完成步骤标记为 skipped。"""
        if not self._plan:
            raise ValueError("Plan not created yet")
        for step in self._plan.steps:
            if step.status in ("pending", "running"):
                step.status = "skipped"
        self._plan.updated_at = datetime.now(timezone.utc).isoformat()
        return self._plan

    def get_ready_steps(self) -> list[PlanStep]:
        """获取所有依赖已满足且状态为 pending 的步骤。"""
        if not self._plan:
            return []
        completed_ids = {s.id for s in self._plan.steps if s.status == "completed"}
        ready = []
        for step in self._plan.steps:
            if step.status != "pending":
                continue
            if all(dep in completed_ids for dep in step.dependencies):
                ready.append(step)
        return ready

    def get_snapshot(self) -> dict:
        """返回 Plan 完整快照（用于 SSE 事件和持久化）。"""
        if not self._plan:
            return {"plan_id": None, "steps": [], "revise_count": 0}
        return {
            "plan_id": self._plan.plan_id,
            "thread_id": self._plan.thread_id,
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "assignee_agent_id": s.assignee_agent_id,
                    "status": s.status,
                    "dependencies": s.dependencies,
                    "note": s.note,
                    "retry_count": s.retry_count,
                    "artifacts": s.artifacts,
                }
                for s in self._plan.steps
            ],
            "created_at": self._plan.created_at,
            "updated_at": self._plan.updated_at,
            "revise_count": self._plan.revise_count,
        }

    def should_revise(self, step_id: str) -> bool:
        """检查某个步骤是否需要触发 revise_plan（retry >= 3）。"""
        if not self._plan:
            return False
        for step in self._plan.steps:
            if step.id == step_id:
                return step.retry_count >= self.MAX_STEP_RETRIES
        return False

    def should_terminate(self) -> bool:
        """检查是否应该终止（revise 次数 >= 3）。"""
        if not self._plan:
            return False
        return self._plan.revise_count >= self.MAX_REVISE_COUNT

    def increment_retry(self, step_id: str) -> int:
        """增加步骤重试计数并返回新值。"""
        if not self._plan:
            return 0
        for step in self._plan.steps:
            if step.id == step_id:
                step.retry_count += 1
                return step.retry_count
        return 0

    @property
    def plan(self) -> Optional[Plan]:
        return self._plan

    @property
    def all_completed(self) -> bool:
        if not self._plan:
            return True
        return all(s.status in ("completed", "failed", "skipped") for s in self._plan.steps)
