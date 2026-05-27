"""
WorkflowLoader —— Skill_Workflow YAML 模板加载器。

从 backend/agent/v2/workflows/ 加载 YAML 模板文件。

满足：R11
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SkillWorkflow:
    id: str
    title: str
    description: str
    default_steps: list[dict] = field(default_factory=list)


class WorkflowLoader:
    """从 workflows/ 目录加载 YAML 模板。"""

    def __init__(self, workflows_dir: Optional[str] = None):
        if workflows_dir is None:
            workflows_dir = str(
                Path(__file__).resolve().parent.parent / "workflows"
            )
        self._dir = Path(workflows_dir)
        self._cache: Optional[list[SkillWorkflow]] = None

    def load_all(self) -> list[SkillWorkflow]:
        """加载所有 YAML 模板。"""
        if self._cache is not None:
            return self._cache

        workflows = []
        if not self._dir.exists():
            self._cache = workflows
            return workflows

        try:
            import yaml
        except ImportError:
            self._cache = workflows
            return workflows

        for file_path in self._dir.glob("*.yaml"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and data.get("id"):
                    workflows.append(SkillWorkflow(
                        id=data["id"],
                        title=data.get("title", data["id"]),
                        description=data.get("description", ""),
                        default_steps=data.get("default_steps", []),
                    ))
            except Exception:
                continue

        self._cache = workflows
        return workflows

    def get(self, skill_id: str) -> Optional[SkillWorkflow]:
        """按 ID 获取单个模板。"""
        all_wf = self.load_all()
        for wf in all_wf:
            if wf.id == skill_id:
                return wf
        return None

    def reload(self) -> None:
        """清除缓存，强制重新加载。"""
        self._cache = None
