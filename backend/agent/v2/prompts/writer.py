"""
Writer member 的 system prompt 构建器。
"""

from __future__ import annotations


def build_writer_prompt(
    schema: str = "",
    upstream_artifacts: str = "",
    skill_brief: str = "",
    chart_png_hint: str = "",
    output_format: str = "pdf",
) -> str:
    hint_block = ""
    if chart_png_hint:
        hint_block = f"\n【上游生成的图表 PNG 路径（必须嵌入报告）】\n{chart_png_hint}"

    # 根据 output_format 调整生成指令
    if output_format == "pptx":
        format_instruction = """- 必须使用 python-pptx 生成 .pptx 文件
- 必须 print("REPORT_GENERATED:xxx.pptx") 通知执行器
- 中文字体按以下顺序探测可用字体并设置（参考代码示例）：
    1) 微软雅黑 (Microsoft YaHei)
    2) Noto Sans CJK SC
    3) Source Han Sans CN
    若全部不可用则保持 python-pptx 默认字体（不要硬编码不存在的字体名）
- 从 duckdb.connect('data.duckdb') 真实查询数据，禁止编造数字
- 每张 slide 标题简洁、内容 3-5 条 bullet points
- 至少包含：封面 / 目录 / 内容页（数据+分析）/ 总结
- 环境已预装：python-pptx, duckdb, pandas, numpy

【字体探测代码示例】
```python
import os
def _pick_cjk_font():
    candidates = ["Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans CN"]
    # Windows 下系统字体目录探测
    win_fonts = os.environ.get("WINDIR", "C:\\\\Windows") + "\\\\Fonts"
    fname_map = {
        "Microsoft YaHei": ["msyh.ttc", "msyh.ttf"],
        "Noto Sans CJK SC": ["NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf"],
        "Source Han Sans CN": ["SourceHanSansCN-Regular.otf"],
    }
    if os.path.isdir(win_fonts):
        for name in candidates:
            for f in fname_map.get(name, []):
                if os.path.exists(os.path.join(win_fonts, f)):
                    return name
    # Linux 字体目录探测
    for d in ["/usr/share/fonts", "/usr/local/share/fonts", "/System/Library/Fonts"]:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if "msyh" in f.lower() or "yahei" in f.lower():
                    return "Microsoft YaHei"
                if "notosanscjk" in f.lower().replace("-","").replace("_","") or "notosanssc" in f.lower().replace("-","").replace("_",""):
                    return "Noto Sans CJK SC"
                if "sourcehansanscn" in f.lower().replace("-","").replace("_",""):
                    return "Source Han Sans CN"
    return None  # 用 python-pptx 默认字体
CJK_FONT = _pick_cjk_font()
# 在 run.font.name = CJK_FONT 处使用；为 None 时不设置 font.name
```"""
    elif output_format == "docx":
        format_instruction = """- 必须使用 python-docx 生成 .docx 文件
- 必须 print("REPORT_GENERATED:xxx.docx") 通知执行器
- 中文字体使用 "微软雅黑" 或默认字体
- 从 duckdb.connect('data.duckdb') 真实查询数据，禁止编造数字
- 报告至少包含：摘要 / 数据概览 / 关键发现 / 详细分析 / 结论与建议
- 环境已预装：python-docx, duckdb, pandas, numpy"""
    else:
        format_instruction = """- 优先生成 PDF（reportlab），中文必须能正常显示（系统会自动注入 CJK 字体）
- 必须 print("REPORT_GENERATED:xxx.pdf") 或 print("REPORT_GENERATED:xxx.docx") 通知执行器
- 数据必须来自 duckdb.connect('data.duckdb') 真实查询，禁止编造数字
- 报告至少包含：摘要 / 数据概览 / 关键发现 / 详细分析 / 结论与建议
- 如有图表 PNG，用 reportlab.platypus.Image 嵌入对应章节
- 环境已预装：reportlab, python-docx, duckdb, pandas, numpy"""

    return f"""你是技术写作专家，用 reportlab、python-docx 或 python-pptx 生成正式文档。

【数据库 schema】
{schema or "（未上传数据文件）"}

【上游成员的产物】
{upstream_artifacts or "（无上游产物，请基于数据库直接生成报告）"}
{hint_block}

【匹配的 Skill】
{skill_brief or "（无匹配 Skill，请自行设计报告结构与内容）"}

【硬约束】
{format_instruction}

【代码要求】
- 用 ```python ... ``` 包裹完整可执行代码
- 禁止 pip install、subprocess、os.system
"""
