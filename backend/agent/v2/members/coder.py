"""
Coder 成员 Agent。

合并 legacy cleaner + analyzer + visualizer + predictor 能力，
统一为"写 Python 处理 DuckDB 数据"。

MTC 升级：检测非表格附件（PDF/PPTX/图片/音视频）时调用 File_Parser。
"""

from __future__ import annotations

import re

from backend.agent.v2.members.base import BaseMember, MemberContext
from backend.agent.v2.prompts.coder import build_coder_prompt


# 关键词 → legacy validator sender alias
# 越靠前越严格（cleaner 要求 xlsx 产物，visualizer 要求图表，依此类推）
_TASK_ALIASES = (
    ("cleaner",     ("清洗", "去重", "缺失值", "去重", "去空", "异常值修正", "format", "清理", "整理")),
    ("visualizer",  ("可视化", "图表", "趋势", "分布", "对比", "chart", "plot")),
    ("predictor",   ("预测", "建模", "聚类", "回归", "model", "predict", "forecast")),
)


def _detect_validator_sender(text: str) -> str:
    """根据 instruction/task 文本推断 legacy validator 期望的 sender。"""
    if not text:
        return "analyzer"
    lowered = text.lower()
    for alias, kws in _TASK_ALIASES:
        for kw in kws:
            if kw in lowered or kw in text:
                return alias
    return "analyzer"


class CoderMember(BaseMember):
    """数据工程师：写 Python 处理 DuckDB，产出清洗文件/图表/分析结论。"""

    name = "coder"
    requires_code_execution = True

    def build_prompt(self, ctx: MemberContext) -> str:
        skill_brief = "（无匹配 Skill）"
        if ctx.skill_name:
            skill_brief = (
                f"已匹配 Skill `{ctx.skill_name}` (capability={ctx.skill_capability}): "
                f"{ctx.extra.get('skill_description', '') or ''}"
            )

        # 注入已解析文件的文本内容
        parsed_texts = ctx.extra.get("parsed_file_texts", "")

        # 把 attached_files 里的表名提炼出来，作为强约束塞到 prompt
        target_tables = []
        for f in ctx.attached_files or []:
            t = (f.get("table_name") or "").strip()
            if t and t not in target_tables:
                target_tables.append(t)

        return build_coder_prompt(
            instruction=ctx.instruction,
            schema=ctx.schema,
            skill_brief=skill_brief,
            parsed_file_texts=parsed_texts,
            target_tables=target_tables,
        )

    def default_reply(self) -> str:
        return "coder 已完成数据处理与代码执行。"

    def _validator_sender_alias(self) -> str:
        """根据任务文本动态映射 sender。

        legacy validator 按 sender 区分校验（cleaner 要 xlsx，visualizer 要图表，
        analyzer 最宽松）。之前一律 "analyzer" 导致清洗任务即使没产出 xlsx 也算通过。
        现在由 _ctx_for_alias() 暂存的 ctx 决定。
        """
        # 优先看运行时上下文
        ctx = getattr(self, "_active_ctx", None)
        if ctx is not None:
            text = (ctx.instruction or "") + " " + (ctx.task_goal or "")
            return _detect_validator_sender(text)
        return "analyzer"

    async def execute(self, ctx, on_event=None):
        # 把 ctx 缓存给 _validator_sender_alias 使用，避免修改 BaseMember 接口
        self._active_ctx = ctx
        try:
            return await super().execute(ctx, on_event=on_event)
        finally:
            self._active_ctx = None

    def needs_file_parser(self, ctx: MemberContext) -> bool:
        """检查上下文是否包含需要 File_Parser 处理的附件。"""
        non_table_mimes = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "image/png", "image/jpeg", "image/jpg",
            "audio/mpeg", "audio/wav",
            "video/mp4", "video/quicktime",
        }
        for f in ctx.attached_files:
            mime = f.get("type", "") or f.get("mime_type", "")
            if mime in non_table_mimes:
                return True
        return False
