先说一个反直觉的事实：你对标的 Trae Solo / Cursor Composer / Claude Code，没有一个是多 Agent 架构。它们都是单 Agent + 丰富工具 + 长程规划循环。多 Agent 这个词在论文里很性感，但在产品里：协调成本远大于专业化收益，除非任务真正在 token 维度上必须分头。

你现在的 Team 模式，本质是用一个 LLM 决策"派给谁"，再让另一个 LLM 干活。这等于让你的产品做两次 LLM 调用、走两套 prompt、分两次上下文，而成果跟一个聪明 Agent 调一次工具没有本质区别。Coder/Writer/Researcher 不是真"成员"，只是三组 prompt + 三套 validator 配置 —— 你完全可以把它们做成单 Agent 的三种工具。

具体到你的代码，差距落在四个地方：

1. Supervisor 的 prompt 是静态决策树 那段"用户请求里出现了 X → assign("coder")"是写死的 if-else。这不是规划，是路由。规划应该是"我先做 A，得到 B 后做 C"，并且记得自己在第几步。

2. 没有 plan / track / replan Supervisor 每一轮只看到 task_goal + schema，看不到"我已经做了什么、还差什么、上一步产物是什么"。所以它每轮都是从零做决策，自然无法处理 5 步以上的任务。

3. 8 轮硬上限 Trae Solo / Claude Code 一个任务跑 50–200 步是常态。你 8 轮，复杂任务必死。

4. Solo 和 Team 是两个独立大脑 Solo 不知道 Coder 存在，Team 不知道 web_search 存在。所以"自动模式"无论怎么调启发式都会有边界 case。这就是你说的"重叠和冲突"的根源。

走向 Trae Solo 那种体验的路径
最直接的办法是：砍掉 Team 模式的多 Agent 架构，把所有能力收进一个 Supervisor Agent，但给它三样东西。

一、统一工具面板（取代多成员）
把现在 Coder/Writer/Researcher 各自独有的能力，全部变成单 Agent 的工具：

当前 Solo 工具:           web_search, crawl_page, search_and_crawl,
                         calculator, summarize_numbers,
                         generate_chart, execute_python

新增的"重型工具":          run_in_sandbox(code)           ← 替代 Coder
                         generate_pdf_report(spec)      ← 替代 Writer，内部用 reportlab
                         generate_docx_report(spec)     ← 替代 Writer，内部用 python-docx
                         search_to_db(query, table)     ← 替代 Researcher 的入库部分
                         query_duckdb(sql)              ← 让 Agent 看自己产物
                         list_tables() / read_table()   ← schema 探索
每个"重型工具"内部还能复用 v2 现有的 executor → validator → fixer 逻辑，所以代码资产不丢。变化在于谁调它：从 supervisor.assign(coder) 变成 supervisor.run_in_sandbox()。少一层间接性，体感就完全不一样了。

二、加一个真正的 Plan / TODO 状态
LLM 第一步强制先调 make_plan(goal) → [step1, step2, step3...]，把任务拆分成 TODO 写入 state。之后每轮可以调：

update_plan(step_id, status) 标记进度
add_step(...) 发现新需求时加步骤
revise_plan(...) 出问题时改路线
这个 plan 在 SSE 里推给前端展示就是"任务进度"。用户能看到 Agent 在干什么、到哪一步、还差什么。Trae Solo 体验的核心就这一个东西。

三、放开步数 + 引入预算管理
max_rounds 改成 token 预算 + 步数双限制（比如 50 步 / 50k tokens）。配合 Plan 的进度条，长任务能跑下去；接近预算时让 Agent 自己决定要不要做"压缩当前进展 + 写阶段性总结"。

我建议的实施分阶段
考虑到你不想推倒重来，又想要质变，我会这样切：

Phase 1（约 2 天工作量，立即去掉模式选择）

前端 ChatView 删掉 Solo / Team / 自动 三个按钮，只保留模型选择
后端只保留一个端点（仍叫 /api/chat 或新建 /api/agent），背后是当前的 Solo 实现
给 Solo 增加 4 个新工具：run_in_sandbox / generate_pdf_report / query_duckdb / list_tables，工具内部就调用 v2 现有的 CoderMember/WriterMember 代码
max_steps 从 15 调到 40
关键：删掉 v2 supervisor / planner / runtime 的"路由"那一层。保留 members 作为工具的内部实现
这一阶段后，你的产品就已经是"单 Agent，统一入口，能干任何事"的形态。前端用户层面看不到模式切换，Agent 层面也只有一种执行路径。

Phase 2（约 3-5 天，达到 Trae Solo 体感）

引入 TodoList 状态：定义 Plan 数据结构，supervisor 必须先调 make_plan
在 SSE 协议里加 plan_update 事件，前端右侧抽屉展示实时 TODO
加 reflect_and_replan 工具，让 Agent 在 fixer 失败 3 次后自己换思路
引入工具调用历史 + 滚动摘要，避免长 thread 上下文爆炸
Phase 3（可选，专业化场景）

当 Phase 2 跑稳后，如果发现某些任务（比如长篇调研报告）确实在一个 Agent 里"心智负担过重"，再回头引入"子任务"概念 —— 但这次是 Agent 主动选择 spawn 子 Agent，不是 supervisor 强制路由。
这才是多 Agent 真正派得上用场的地方：长任务里 Agent 自己说"这块太复杂，我开个独立上下文做"。
关于现在这套 v2 代码
不要全扔。v2 的 executor → validator → fixer 自检循环是真正有价值的资产，那是一年踩坑攒出来的产物校验逻辑（PDF 必须含图、xlsx 必须导出、运行错误自动修等）。Phase 1 改造时，把这套逻辑包成"工具的内部实现"，从外层看就是 run_in_sandbox(code) 一个调用，但内部还是三段式自检。

要砍的是 supervisor.py / planner.py / runtime.py 那个路由层，那才是负担。

一个具体决策点
你需要先回答一个问题，再决定 Phase 1 的边界：

Skill Registry / .trae/skills/ 这套要不要保留？

它现在是 Writer 在用，能从 analysis-report / product-planning / pdf-autofill 这些目录里读 SKILL.md 模板。

要保留 → Phase 1 里的 generate_pdf_report 工具内部继续接 Skill 匹配
不要保留 → 直接让 LLM 现写 reportlab 代码，删掉整个 skill_registry 子系统（300 行不到）
我倾向不要保留：现在用着的几个 skill 内容很薄，更像一组示例 prompt 片段，跟"动态创建/复用 skill"这个原始愿景差得很远。删了之后 Writer 工具变成一段干净的"调 LLM 写 reportlab 代码 → 沙盒执行 → 校验产物"，没那么多概念。

要不要我从 Phase 1 开始动手？第一步先做这个：

把 pickAgentMode 整个删掉，前端固定调一条新端点
给 single_agent 加 run_in_sandbox 工具，内部接 v2 的 CoderMember 实现
ChatView 上去掉模式按钮