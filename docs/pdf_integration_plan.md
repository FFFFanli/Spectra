# PDF 能力接入方案

## 1. 背景

项目内已引入 `pdf/` 目录，其中 [SKILL.md](file:///d:/project/LangGraph多Agent数据分析报告系统/pdf/SKILL.md) 定义了一个通用 `pdf` skill。该 skill 不是单纯的“报告生成器”，而是一套覆盖 PDF 读写、提取、表单填写、OCR、创建与合并的通用能力说明。

当前项目已经具备以下基础：

- LangGraph 多 Agent 工作流
- 代码执行与自动修复闭环
- 图表产物回收与前端展示
- 文件下载区与报告产物通道
- `reportlab`、`weasyprint`、`python-docx` 等依赖

因此最合理的接入方式不是把 `pdf/` 目录当成一个孤立功能，而是将其拆成两层：

- 上层：`reporter_agent` 负责理解“生成什么报告”
- 下层：`pdf` 目录提供“如何生成/处理 PDF”的实现参考

## 2. 对 `pdf/` 目录的能力拆解

### 2.1 已确认的通用能力

来自 [SKILL.md](file:///d:/project/LangGraph多Agent数据分析报告系统/pdf/SKILL.md)：

- 创建新 PDF
- 从 PDF 中提取文本和表格
- 合并、拆分、旋转、加密/解密 PDF
- 提取图片
- 扫描版 PDF OCR
- 填写 PDF 表单

### 2.2 当前项目直接可复用的部分

适合立即接入报告生成功能的能力：

- `reportlab` 创建多页 PDF
- `reportlab` 表格排版
- `pdfplumber` / `pypdf` 作为后续提取与检查能力
- `qpdf` 作为后续 PDF 合并/优化能力

### 2.3 暂不直接接入的部分

来自 [forms.md](file:///d:/project/LangGraph多Agent数据分析报告系统/pdf/forms.md) 的表单填写流程，当前不属于数据分析报告主链路，先保留为二期能力：

- 可填写字段检测
- 表单字段提取
- 基于坐标的注释填表
- 表单输出验证图

## 3. 接入目标

第一期目标：让系统能够识别“生成报告 / 生成 PDF / 年报 / 财务分析报告”等请求，并自动产出可下载 PDF。

期望结果：

- 用户请求报告时，Supervisor 将任务路由到 `reporter_agent`
- `reporter_agent` 生成分析代码和 PDF 报告代码
- Executor 执行后自动识别 `.pdf` / `.docx` 产物
- Validator 校验报告是否成功生成
- 前端工作台自动展示 PDF / Word 下载入口

## 4. 第一期开发表

### 4.1 工作流改造

- 新增 `reporter_agent`
- Supervisor 增加 `reporter` 路由判断
- LangGraph 增加 `reporter -> executor -> validator` 链路
- Validator 增加“报告任务必须产出 PDF/报告文件”的校验规则

### 4.2 报告生成策略

`reporter_agent` 采用 LLM 生成 Python 代码，但要求遵循 `pdf` skill 中的能力约束：

- 优先使用 `reportlab`
- 支持中文字体回退
- 生成多页 PDF
- 可选生成图表 PNG/HTML 并插入报告
- 必须输出用户可读摘要
- 必须保存 PDF，并通过标准输出声明产物路径

### 4.3 产物规范

统一产物规范：

- 图表：`chart_xxx.html`、`chart_xxx.png`
- Word 报告：`report_xxx.docx`
- PDF 报告：`report_xxx.pdf`

执行器需要自动识别这些文件并移动到 `artifacts/`。

## 5. 第二期规划

第二期再逐步接入 `pdf/` 目录中的高级能力：

- PDF 模板驱动的封面页生成
- 目录页自动生成与页码回填
- 使用 `qpdf` 合并封面 / 正文 / 附录
- 导出后自动做结构化质检
- 读取用户上传 PDF 并抽取表格继续分析
- PDF 表单自动填写

## 6. 本次实际落地范围

本次代码改造只做第一期最小闭环：

- 新增 `reporter_agent`
- 报告请求可被路由
- 报告产物可被识别与校验
- 前端延续现有下载区展示能力，无需额外改造

## 7. 风险与约束

- `reporter_agent` 目前仍然依赖大模型生成最终 PDF 代码，质量受提示词稳定性影响
- 中文字体在不同环境中可能存在差异，需要在生成代码中提供字体回退链
- 如果未来要追求“像智普清言一样”的稳定体验，建议将封面、目录、页脚、章节模板逐步沉淀为确定性代码，而不是完全依赖 LLM 即时生成

## 8. 结论

`pdf/` 目录非常适合作为当前项目的 PDF 能力底座，但它更适合充当“文档处理能力层”，而不是独立承担“企业分析报告产品能力”。

本项目应采用：

- `reporter_agent` 负责报告任务规划与代码生成
- `pdf/` 目录负责提供 PDF 处理规范与技术参考

这也是当前最贴近“智普清言式分析报告生成体验”的演进路线。
