# Skill-Driven Runtime Architecture

> ⚠️ **历史文档（v1 时代）**：本文档描述的是已下线的 v1 多 Agent 架构（`backend/agents.py` + `backend/graph.py`）。
> 当前 Team Supervisor 已替换为 v2 实现（`backend/agent/v2/`），成员被合并为 `coder / writer / researcher / responder` 四类，
> 原本的 `reporter / planner / form_filler` 通过 `backend/agent/v2/infra/skills.py` 中的 `_AGENT_ALIAS_MAP`
> 全部归属到 v2 的 `writer`。Skill Registry / Skill Builder 的核心理念在 v2 仍保留。
>
> 仅作为历史背景保留，不要据此修改代码。

## 目标

当前项目的目标不是继续堆叠固定模板功能，而是把“分析报告生成”“产品规划方案”“PDF 智能填充”统一收敛为一个真正的多 Agent 运行时：

- `Supervisor` 先理解用户实时需求
- 根据任务语义选择目标 `Agent`
- 通过 `Skill Registry` 查找最合适的 skill
- 如果没有可复用 skill，则进入 `skill_builder`
- `skill_builder` 自动创建新 skill 并回交给目标 Agent
- 目标 Agent 再基于 skill 和当前上下文实时生成代码与产物

## 运行链路

### 1. Supervisor

`backend/agents.py` 中的 `supervisor_agent()` 负责两件事：

- 判断需求属于 `cleaner / analyzer / visualizer / predictor / reporter / planner / form_filler`
- 对 `reporter / planner / form_filler` 这类 skill-driven Agent 预选 skill

如果命中已有 skill，Supervisor 直接把 skill 信息写入状态：

- `selected_skill_name`
- `selected_skill_path`
- `selected_skill_description`
- `selected_skill_capability`

如果没有命中，Supervisor 不直接执行，而是把流程转到：

- `next_node = "skill_builder"`
- `target_agent = "<目标 Agent>"`

### 2. Skill Registry

`backend/skill_registry.py` 负责 skill 的完整生命周期：

- 确保内置 skill 存在
- 从 `.trae/skills/*/SKILL.md` 加载 skill
- 基于触发词、描述、能力标签做语义匹配
- 在无匹配时自动创建 skill

当前内置 skill：

- `analysis-report`
- `product-planning`
- `pdf-autofill`

关键约束：

- skill 不能仅因为 `owning_agent` 相同就命中
- 必须先有语义命中，再叠加 agent 权重
- 这样才能真正触发“没有 skill 就创建”

### 3. Skill Builder

`skill_builder_agent()` 是动态扩展入口。

它会根据本次请求：

- 生成新的 skill 名称
- 推断 capability
- 生成 `.trae/skills/<skill-name>/SKILL.md`
- 把新建 skill 回写到图状态中

随后图路由回目标 Agent：

- `reporter`
- `planner`
- `form_filler`

### 4. Skill-Driven Agent

文档类 Agent 不再优先走固定模板，而是统一走 skill 驱动：

- `reporter_agent()`
- `planner_agent()`
- `form_filler_agent()`

其中：

- `reporter` 根据 skill 实时生成分析报告代码
- `planner` 根据 skill 实时生成产品规划方案代码
- `form_filler` 基于 skill 调用 PDF 自动填充引擎

这类 Agent 的 prompt 中必须明确：

- 不套用固定模板
- 结合用户输入和数据源动态生成结构
- 优先输出正式 PDF
- 通过标准产物标记向执行器声明输出

## Graph 节点

`backend/graph.py` 当前新增了以下节点：

- `planner`
- `form_filler`
- `skill_builder`

关键状态字段：

- `selected_skill_name`
- `selected_skill_path`
- `selected_skill_description`
- `selected_skill_capability`
- `skill_auto_created`
- `target_agent`

图路由逻辑现在支持：

- `supervisor -> reporter/planner/form_filler`
- `supervisor -> skill_builder -> reporter/planner/form_filler`
- `agent -> executor -> validator -> fixer`

## 与旧模板逻辑的关系

项目里仍保留了一部分历史模块，例如：

- `backend/report_templates.py`

这些模块不应再作为主入口使用，而应视为：

- 兼容历史实现的 fallback
- 可逐步下沉为库函数
- 或在后续重构中继续拆分为 skill 片段

当前约束：

- 产品规划默认必须走实时 skill 生成，不保留旧模板引擎入口

推荐原则：

- 主路由只认 `Supervisor + Skill Registry + Skill Builder + Agent`
- 固定模板只作为“无法实时生成时的保底能力”
- 新需求不要再往旧模板模块追加硬编码分支

## 测试策略

建议至少覆盖以下场景：

- Supervisor 能为报告/规划/PDF 填充正确选路
- 无匹配 skill 时会进入 `skill_builder`
- `skill_builder` 能真实创建 skill 文件
- `reporter/planner/form_filler` 能消费 selected skill
- validator 能校验文档类任务必须生成可下载产物

## 后续建议

下一阶段可以继续推进三件事：

1. 把旧模板模块改造成可插拔 fallback skill
2. 为 skill 增加版本、来源和质量评分
3. 在前端展示“当前使用的 agent / skill / 是否自动创建”
