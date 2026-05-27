"""
TeamMTCRuntime —— MTC 风格统一执行体。

完整的请求生命周期：
  1. File_Parser 解析附件 → emit file_parsed
  2. 问候判断 → fast-path 或继续
  3. LLM make_plan → emit plan_created
  4. Scheduler 循环 → emit step_started/completed/failed
  5. Reviewer/Responder 最终回复 → emit reply
  6. emit done

满足：R2, R3, R5, R6, R7, R9, R11, R12
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, AsyncIterator, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.v2.llm import _create_llm
from backend.agent.v2.members.base import MemberContext
from backend.agent.v2.members.coder import CoderMember
from backend.agent.v2.members.researcher import ResearcherMember
from backend.agent.v2.members.writer import WriterMember
from backend.agent.v2.members.responder import ResponderMember
from backend.agent.v2.members.designer import DesignerMember
from backend.agent.v2.members.reviewer import ReviewerMember
from backend.agent.v2.mtc.plan_manager import PlanManager, PlanStep
from backend.agent.v2.mtc.scheduler import PlanScheduler
from backend.agent.v2.mtc.file_parser import get_file_parser, ParsedFileRecord
from backend.agent.v2.mtc.background_tasks import BackgroundTaskManager
from backend.agent.v2.mtc.sse_translator import SSETranslator
from backend.agent.v2.mtc.context_manager import ContextManager
from backend.agent.v2.mtc.persistence import PlanPersistence, TaskPersistence, init_db
from backend.agent.v2.mtc.workflow_loader import WorkflowLoader
from backend.request_context import get_request_model


# 问候词列表（匹配则跳过 Plan 生成）
GREETING_WORDS = {
    "你好", "hello", "hi", "hey", "嗨", "早上好", "下午好", "晚上好",
    "good morning", "good afternoon", "good evening",
    "谢谢", "thanks", "thank you", "再见", "bye", "goodbye",
    "在吗", "在不在", "ok", "okay", "好的", "嗯", "哦",
}


class TeamMTCRuntime:
    """MTC 风格统一执行体 —— 一次请求 → 自动 Plan → 并行调度 → 产物交付。"""

    MAX_LLM_CALLS = 50

    def __init__(self):
        self._plan_manager: Optional[PlanManager] = None
        self._scheduler: Optional[PlanScheduler] = None
        self._file_parser = get_file_parser()
        self._bg_task_manager = BackgroundTaskManager()
        self._sse_translator = SSETranslator()
        self._context_manager = ContextManager()
        self._plan_persistence = PlanPersistence()
        self._task_persistence = TaskPersistence()
        self._workflow_loader = WorkflowLoader()
        self._llm_call_count = 0
        self._events: list[dict] = []  # 积压事件队列
        self._artifacts: list[dict] = []
        self._plan_snapshot: Optional[dict] = None

        # Member agents
        self._members = {
            "coder": CoderMember(),
            "writer": WriterMember(),
            "researcher": ResearcherMember(),
            "responder": ResponderMember(),
            "designer": DesignerMember(),
            "reviewer": ReviewerMember(),
        }

        # 初始化数据库表
        try:
            init_db()
        except Exception:
            pass

    async def run(
        self,
        user_message: str,
        thread_id: str,
        schema: str = "",
        conversation_history: Optional[list] = None,
        attached_files: Optional[list] = None,
        skill_workflow_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """主入口：接收用户消息，实时 yield SSE 事件直到完成。

        采用 asyncio.Queue 把内部 emit 与 SSE yield 解耦：
          - emit_internal 把事件 push 进 queue（非阻塞）
          - 主入口在后台跑 _run_pipeline，前台不停 await queue.get() 并 yield
          - pipeline 结束时 push None 哨兵
        这样能保证调度循环、LLM 调用产生的事件实时下发到客户端，
        而不是积压到流末尾才一次性输出。
        """
        self._plan_manager = PlanManager(thread_id)
        self._scheduler = PlanScheduler(self._plan_manager)
        self._bg_task_manager.set_emit_fn(self._emit_internal)
        # 把 schema 缓存到实例上，让 _execute_step 在构建 MemberContext 时用到
        self._schema = schema or ""
        self._attached_files = attached_files or []

        # 注册后台任务执行函数（同步包装，在 thread pool 中运行）
        def _bg_execute(agent_id: str, task_desc: str, task_thread_id: str) -> dict:
            """同步入口：在新 event loop 中跑 member.execute()。"""
            member = self._members.get(agent_id)
            if member is None:
                return {"status": "failed", "reply": "", "artifacts": [],
                        "error": f"未知 agent_id: {agent_id}"}
            ctx = MemberContext(
                instruction=task_desc,
                task_goal=f"后台任务: {task_desc[:100]}",
                thread_id=task_thread_id,
                schema=getattr(self, '_schema', '') or '',
                attached_files=getattr(self, '_attached_files', []) or [],
            )
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(member.execute(ctx))
                return {
                    "status": result.status,
                    "reply": result.reply or member.default_reply(),
                    "artifacts": result.artifacts or [],
                    "error": result.error or "",
                }
            finally:
                loop.close()

        self._bg_task_manager.set_execute_fn(_bg_execute)
        self._llm_call_count = 0
        self._artifacts = []
        self._events = []  # 兼容旧调用，但真正的事件通过 queue 流出

        # 实时事件队列（单消费者：本协程的 yield 循环）
        self._event_queue: asyncio.Queue = asyncio.Queue()

        async def pipeline():
            try:
                attached_files_local = attached_files or []

                # 1. File_Parser 解析附件
                self._last_parsed_records: list[ParsedFileRecord] = []
                for f in attached_files_local:
                    file_path = f.get("path", "")
                    mime_type = f.get("type", "") or f.get("mime_type", "")
                    if file_path and mime_type:
                        record = await self._file_parser.parse(file_path, mime_type)
                        self._last_parsed_records.append(record)
                        self._emit_internal("file_parsed", {
                            "file_id": record.file_id,
                            "mime_type": record.mime_type,
                            "summary": record.summary,
                            "preview_payload": record.preview_payload,
                        })

                parsed_texts = "\n".join(
                    f"[{r.file_id}] {r.summary}\n{r.extracted_text}"
                    for r in self._last_parsed_records
                )

                # 2. 问候判断
                if self._is_greeting(user_message):
                    await self._fast_respond(user_message, thread_id)
                    return

                # 3. Plan 创建阶段
                plan_created = await self._create_plan(
                    user_message=user_message,
                    thread_id=thread_id,
                    schema=schema,
                    parsed_texts=parsed_texts,
                    skill_workflow_id=skill_workflow_id,
                )

                if not plan_created:
                    await self._fast_respond(user_message, thread_id)
                    return

                # 4. Scheduler 循环
                await self._scheduler.run_plan(
                    execute_step_fn=self._execute_step,
                    emit_fn=self._emit_internal,
                    on_revise_needed=self._on_revise_needed,
                )

                # 5. 最终回复
                await self._finalize()
            except Exception as e:
                self._emit_internal("error", {"message": str(e)})
            finally:
                # 5. 收尾：build done 事件，然后 push None 哨兵关闭流
                done_evt = self._build_done_event(thread_id)
                await self._event_queue.put(done_evt)
                await self._event_queue.put(None)  # 哨兵

        pipeline_task = asyncio.create_task(pipeline())

        try:
            while True:
                evt = await self._event_queue.get()
                if evt is None:
                    break
                yield evt
        finally:
            # 确保 pipeline 完成（即使消费者提早 break）
            if not pipeline_task.done():
                pipeline_task.cancel()
                try:
                    await pipeline_task
                except (asyncio.CancelledError, Exception):
                    pass

    # ── Token tracking & context compression ─────────────────────

    def _extract_input_tokens(self, response) -> int:
        """从 LangChain 响应中提取输入 token 数。

        优先级：response_metadata.token_usage / usage → usage_metadata。
        当一个来源未给出有效数字时（None/0/空 dict），fall through 到下一个。
        """
        # 1. response_metadata.token_usage / usage
        try:
            meta = getattr(response, "response_metadata", None) or {}
            usage = meta.get("token_usage") or meta.get("usage")
            if isinstance(usage, dict):
                tokens = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                if tokens:
                    return tokens
        except Exception:
            pass
        # 2. langchain 1.x 标准化字段：usage_metadata
        try:
            usage_meta = getattr(response, "usage_metadata", None)
            if usage_meta and isinstance(usage_meta, dict):
                tokens = usage_meta.get("input_tokens") or 0
                if tokens:
                    return tokens
        except Exception:
            pass
        return 0

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算文本 token 数（中文按 1.5 字符/token，英文按 4 字符/token）。"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if '一' <= c <= '鿿')
        other_chars = len(text) - chinese_chars
        return int(chinese_chars / 1.5 + other_chars / 4)

    def _track_and_check_compress(self, input_tokens: int) -> bool:
        """跟踪 tokens 并检查是否需要压缩。返回 True 表示已触发压缩。"""
        self._context_manager.add_tokens(input_tokens)
        if self._context_manager.should_compress():
            self._context_manager.reset()
            return True
        return False

    # ── Private helpers ──────────────────────────────────────────

    def _emit_internal(self, event_type: str, data: dict) -> None:
        """将内部事件实时推送到 queue（同时维护 artifacts/persistence 等副作用）。"""
        evt = {"event": event_type, "data": data}

        # 优先实时推送到 queue（非阻塞）
        q = getattr(self, "_event_queue", None)
        if q is not None:
            try:
                q.put_nowait(evt)
            except Exception:
                # 兜底：保留 events 数组用于回放
                self._events.append(evt)
        else:
            self._events.append(evt)

        # 收集 artifacts
        if event_type == "step_completed" and data.get("artifacts"):
            for a in data["artifacts"]:
                if a not in self._artifacts:
                    self._artifacts.append(a)

        # 持久化 Plan 快照
        if event_type in ("plan_created", "plan_updated", "plan_revised", "plan_finished"):
            try:
                snapshot = self._plan_manager.get_snapshot()
                self._plan_persistence.save_plan(snapshot)
            except Exception:
                pass

    def _build_done_event(self, thread_id: str) -> dict:
        """构造 done 事件（不直接 yield，由调用方处理）。

        约定：与 _emit_internal 一致——data 始终是 dict（不要预序列化），
        由 api.py 层统一 json.dumps。否则 `{**event_data, ...}` 在 api.py 端会炸。
        """
        plan_snapshot = self._plan_manager.get_snapshot() if self._plan_manager else {}
        return {
            "event": "done",
            "data": {
                "thread_id": thread_id,
                "plan": plan_snapshot,
                "artifacts": self._artifacts,
                "background_tasks": [],
                "runtime_variant": "mtc",
            },
        }

    def _is_greeting(self, msg: str) -> bool:
        """判断是否为纯问候。"""
        stripped = msg.strip().lower()
        if len(stripped) <= 5:
            return True
        if stripped in GREETING_WORDS:
            return True
        # 检查是否为纯标点/表情
        if all(c in "，。！？、；：""''（）…—·～?!.,;:()\"' \t\n\r" for c in msg.strip()):
            return True
        return False

    async def _fast_respond(self, user_message: str, thread_id: str) -> None:
        """问候 fast-path：直接由 Responder 回复。"""
        responder = self._members["responder"]
        ctx = MemberContext(
            instruction=user_message,
            task_goal="简单问候回复",
            thread_id=thread_id,
        )
        result = await responder.execute(ctx)
        self._emit_internal("reply", {"text": result.reply})

    async def _create_plan(
        self,
        user_message: str,
        thread_id: str,
        schema: str,
        parsed_texts: str,
        skill_workflow_id: Optional[str],
    ) -> bool:
        """调用 LLM 创建 Plan。支持 Skill_Workflow 模板。"""
        from backend.agent.v2.mtc.plan_tools import make_plan as make_plan_tool

        # 检查 Skill_Workflow 模板
        template_steps = None
        if skill_workflow_id:
            wf = self._workflow_loader.get(skill_workflow_id)
            if wf:
                template_steps = wf.default_steps

        llm = _create_llm(temperature=0.1)
        llm_with_tools = llm.bind_tools([make_plan_tool])

        # 构建 system prompt
        system_prompt = self._build_plan_system_prompt(
            schema=schema,
            parsed_texts=parsed_texts,
            template_steps=template_steps,
            skill_workflow_id=skill_workflow_id,
        )

        # 最多重试 2 次
        for attempt in range(3):
            self._llm_call_count += 1
            try:
                response = llm_with_tools.invoke([
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ])

                # 跟踪 token 用量
                input_tokens = self._extract_input_tokens(response)
                if not input_tokens:
                    input_tokens = self._estimate_tokens(system_prompt) + self._estimate_tokens(user_message)
                self._track_and_check_compress(input_tokens)

                tool_calls = getattr(response, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        if tc.get("name") == "make_plan":
                            args = tc.get("args", {})
                            steps = args.get("steps", [])

                            # 空 steps 视为无效，重试
                            if not steps:
                                if attempt < 2:
                                    system_prompt += "\n\n【强制指令】make_plan 的 steps 参数不能为空数组，必须包含至少 1 个步骤。"
                                    break  # 跳出 tool_calls 循环，进入下一次 attempt
                                else:
                                    steps = [{"description": user_message, "assignee_agent_id": "responder"}]

                            # 模板校验
                            if template_steps is not None:
                                if len(steps) != len(template_steps):
                                    # 数量不一致，使用模板原始步骤
                                    steps = template_steps
                                    template_validated = False
                                else:
                                    template_validated = True
                                self._plan_manager.create_plan(steps)
                                self._emit_internal("plan_created", {
                                    "plan_id": self._plan_manager.plan.plan_id,
                                    "steps": self._plan_manager.get_snapshot()["steps"],
                                    "template_validated": template_validated,
                                })
                                return True

                            # 非模板路径
                            self._plan_manager.create_plan(steps)
                            self._emit_internal("plan_created", {
                                "plan_id": self._plan_manager.plan.plan_id,
                                "steps": self._plan_manager.get_snapshot()["steps"],
                            })
                            return True

                # 未调用 make_plan，重试时追加强制指令
                if attempt < 2:
                    system_prompt += "\n\n【强制指令】你必须调用 make_plan 工具来创建任务计划。不调用工具无法继续处理。"
                # 检查压缩（避免重试时 prompt 不断膨胀）
                if self._context_manager.should_compress():
                    self._context_manager.reset()
            except Exception as e:
                if attempt >= 2:
                    break

        # 3 次重试后兜底：自动构造 1 步 Plan
        self._plan_manager.create_plan([
            {"description": user_message, "assignee_agent_id": "responder"}
        ])
        self._emit_internal("plan_created", {
            "plan_id": self._plan_manager.plan.plan_id,
            "steps": self._plan_manager.get_snapshot()["steps"],
            "fallback": True,
        })
        return True

    def _build_plan_system_prompt(
        self,
        schema: str,
        parsed_texts: str,
        template_steps: Optional[list],
        skill_workflow_id: Optional[str],
    ) -> str:
        """构建 Plan 创建阶段的 system prompt。"""
        # 从 attached_files 提取表名让 plan step description 显式引用
        attached_files = getattr(self, "_attached_files", []) or []
        target_tables = []
        for f in attached_files:
            t = (f.get("table_name") or "").strip()
            if t and t not in target_tables:
                target_tables.append(t)

        prompt = """你是任务规划专家。根据用户需求，使用 make_plan 工具拆解任务为有序步骤。

每条步骤必填字段：
  - description (str): 步骤描述
  - assignee_agent_id (str): coder / writer / researcher / responder / designer / reviewer
  - dependencies (list[str], 可选): 依赖的步骤描述索引

Agent 类型说明：
  - coder: 写代码处理数据、生成图表
  - writer: 生成 PDF/DOCX/PPTX 报告
  - researcher: 搜索互联网获取信息
  - responder: 直接回复用户（简单问答）
  - designer: 设计 PPT 大纲与版式
  - reviewer: 复核产物质量

规划原则：
  - 步骤数适中（3-10 步）
  - 有依赖关系的步骤必须标注 dependencies
  - 无依赖关系的步骤会被并行执行
  - 最后一步应是 reviewer 或 responder（产出最终回复）
"""

        if target_tables:
            prompt += (
                f"\n\n【⚠️ 数据来源约束（务必遵守）】\n"
                f"本次请求只能操作用户上传的目标表："
                f"{', '.join('`' + t + '`' for t in target_tables)}\n"
                f"每条涉及数据的步骤 description 末尾必须用「针对表 `{target_tables[0]}`」形式显式注明目标表。"
                f"\n禁止 step 提及 `search_results` / `daily_news` 等其它表名，"
                f"即便它们存在于 DuckDB。"
            )

        if template_steps:
            prompt += f"\n\n【Skill 模板】当前使用工作流: {skill_workflow_id}"
            prompt += f"\n模板预定义步骤 ({len(template_steps)} 步):"
            for i, s in enumerate(template_steps):
                prompt += f"\n  {i+1}. {s['description']} → {s['assignee_agent_id']}"
            prompt += "\n请参考模板步骤调用 make_plan，可以调整描述但不要增删步骤。"

        if schema:
            prompt += f"\n\n【可用数据表】\n{schema}"

        if parsed_texts:
            prompt += f"\n\n【已解析的附件内容】\n{parsed_texts}"

        return prompt

    # ── Step execution ───────────────────────────────────────────

    async def _execute_step(self, step: PlanStep) -> dict:
        """执行单个 Plan_Step，调度对应的 Member_Agent。"""
        member = self._members.get(step.assignee_agent_id)
        if member is None:
            return {
                "status": "failed",
                "error": f"未知 agent_id: {step.assignee_agent_id}",
            }

        self._llm_call_count += 1
        if self._llm_call_count > self.MAX_LLM_CALLS:
            self._emit_internal("plan_finished", {
                "finish_reason": "max_llm_calls",
                "summary": f"LLM 调用次数已达上限 ({self.MAX_LLM_CALLS})",
            })
            return {"status": "ok", "reply": "LLM 调用次数已达上限"}

        # 检查上下文压缩
        if self._context_manager.should_compress():
            self._context_manager.reset()

        self._emit_internal("member_status", {
            "agent_id": step.assignee_agent_id,
            "state": "running",
            "current_step_id": step.id,
        })

        # 构建 MemberContext
        ctx = MemberContext(
            instruction=step.description,
            task_goal=f"执行 Plan 步骤: {step.description}",
            thread_id=self._plan_manager._thread_id,
            schema=getattr(self, '_schema', '') or '',
            attached_files=getattr(self, '_attached_files', []) or [],
            upstream_artifacts=step.artifacts,
        )

        try:
            # Coder 检测是否需要 File_Parser
            if isinstance(member, CoderMember) and member.needs_file_parser(ctx):
                # 将已解析的文本注入 coder context
                parsed_texts_for_step = []
                for rec in getattr(self, '_last_parsed_records', []):
                    parsed_texts_for_step.append(rec.extracted_text)
                ctx.extra["parsed_file_texts"] = "\n".join(parsed_texts_for_step)

            result = await member.execute(ctx)

            # 估算 member LLM 调用的 token 用量
            prompt_text = member.build_prompt(ctx)
            estimated_tokens = self._estimate_tokens(prompt_text) + self._estimate_tokens(step.description)
            self._track_and_check_compress(estimated_tokens)

            self._emit_internal("member_status", {
                "agent_id": step.assignee_agent_id,
                "state": "idle",
                "current_step_id": None,
            })
            return {
                "status": result.status,
                "reply": result.reply or "",
                "artifacts": result.artifacts or [],
                "error": result.error or "",
            }
        except Exception as e:
            self._emit_internal("member_status", {
                "agent_id": step.assignee_agent_id,
                "state": "failed",
                "current_step_id": step.id,
            })
            return {
                "status": "failed",
                "error": str(e),
            }

    async def _on_revise_needed(self, reason: str) -> None:
        """触发 LLM revise_plan。"""
        if self._plan_manager.should_terminate():
            self._emit_internal("error", {
                "message": f"任务无法恢复: Plan 已重排 {self._plan_manager.MAX_REVISE_COUNT} 次",
            })
            return

        # 调用 LLM 生成新步骤
        from backend.agent.v2.mtc.plan_tools import revise_plan as revise_plan_tool

        llm = _create_llm(temperature=0.1)
        llm_with_tools = llm.bind_tools([revise_plan_tool])

        self._llm_call_count += 1
        try:
            snapshot = self._plan_manager.get_snapshot()
            sys_prompt = f"Plan 执行遇到问题: {reason}。请调用 revise_plan 重排剩余步骤。\n当前 Plan: {json.dumps(snapshot, ensure_ascii=False)}"
            response = llm_with_tools.invoke([
                SystemMessage(content=sys_prompt),
                HumanMessage(content=f"问题: {reason}，请重排未完成的步骤。"),
            ])

            input_tokens = self._extract_input_tokens(response)
            if not input_tokens:
                input_tokens = self._estimate_tokens(sys_prompt) + self._estimate_tokens(reason)
            self._track_and_check_compress(input_tokens)

            tool_calls = getattr(response, "tool_calls", None)
            if tool_calls:
                for tc in tool_calls:
                    if tc.get("name") == "revise_plan":
                        args = tc.get("args", {})
                        new_steps = args.get("new_steps", [])
                        self._plan_manager.revise_plan(
                            reason=args.get("reason", reason),
                            new_steps=new_steps,
                        )
                        self._emit_internal("plan_revised", {
                            "plan_id": self._plan_manager.plan.plan_id,
                            "reason": reason,
                            "steps": self._plan_manager.get_snapshot()["steps"],
                        })
                        return
        except Exception:
            pass

    async def _finalize(self) -> None:
        """最终回复：Reviewer 或 Responder 产出最终回复。"""
        plan = self._plan_manager.plan
        if not plan:
            return

        # 收集所有步骤的回复
        all_replies = []
        for step in plan.steps:
            if step.status == "completed" and step.note:
                all_replies.append(f"[{step.assignee_agent_id}] {step.note}")

        # 用 Responder 生成最终回复
        summary = "\n".join(all_replies) if all_replies else "任务已完成"
        responder = self._members["responder"]
        ctx = MemberContext(
            instruction=f"根据以下步骤结果生成最终回复摘要:\n{summary}",
            task_goal="生成最终回复",
            thread_id=self._plan_manager._thread_id,
        )
        result = await responder.execute(ctx)
        self._emit_internal("reply", {"text": result.reply})

        # 持久化 Plan 快照
        try:
            self._plan_persistence.save_plan(self._plan_manager.get_snapshot())
        except Exception:
            pass
