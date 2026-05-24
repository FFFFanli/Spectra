"""
图表生成 LangChain Tool —— Agent 可直接生成 Plotly 可视化

特性:
  - 安全的数据输入解析 (CSV/JSON 字符串)
  - 智能图表类型推荐
  - 自动应用暗色主题
  - 返回 HTML 和 PNG 双格式路径
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from langchain_core.tools import tool

from backend.app_paths import ARTIFACTS_DIR, artifact_relpath, ensure_directories


def _parse_data(data_input: str) -> tuple[dict, str]:
    """
    解析用户输入的数据字符串,返回 (columns, rows) 结构。
    支持格式: JSON 二维数组、JSON 对象数组、带表头的 CSV 行
    """
    data_input = data_input.strip()

    # Try JSON array of arrays
    try:
        arr = json.loads(data_input)
        if isinstance(arr, list) and len(arr) > 0:
            if all(isinstance(row, list) for row in arr):
                return {"headers": [f"列{i+1}" for i in range(len(arr[0]))], "rows": arr}, "json_table"
            if all(isinstance(row, dict) for row in arr):
                headers = list(arr[0].keys())
                rows = [[row.get(h, "") for h in headers] for row in arr]
                return {"headers": headers, "rows": rows}, "json_objects"
    except (json.JSONDecodeError, ValueError):
        pass

    # Try CSV
    lines = [l.strip() for l in data_input.split("\n") if l.strip()]
    if len(lines) >= 2:
        headers = [h.strip().strip('"') for h in lines[0].split(",")]
        rows = []
        for line in lines[1:]:
            vals = [v.strip().strip('"') for v in line.split(",")]
            rows.append(vals)
        if rows:
            return {"headers": headers, "rows": rows}, "csv"

    raise ValueError("无法解析输入数据。支持: JSON 二维数组、JSON 对象数组、CSV 格式。")


def _smart_chart_type(headers: list[str], rows: list[list]) -> str:
    """根据数据特征推荐图表类型"""
    num_cols = 0
    cat_cols = 0

    for col_idx, header in enumerate(headers):
        all_num = True
        for row in rows:
            if col_idx < len(row):
                try:
                    float(str(row[col_idx]))
                except (ValueError, TypeError):
                    all_num = False
                    break
        if all_num:
            num_cols += 1
        else:
            cat_cols += 1

    if cat_cols == 1 and num_cols >= 1:
        return "bar"
    if cat_cols == 1 and num_cols >= 1 and len(rows) > 5:
        return "line"
    if num_cols >= 2 and cat_cols == 0:
        return "scatter"
    if cat_cols >= 2:
        return "bar"
    return "bar"


def _generate_chart_code(chart_type: str, headers: list[str], rows: list[list], title: str) -> str:
    """生成 Plotly 图表代码"""
    data_json = json.dumps({"headers": headers, "rows": rows}, ensure_ascii=False)
    chart_id = uuid.uuid4().hex[:8]

    code = f'''# CHART_GENERATION_V1
import json
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

data = json.loads({json.dumps(data_json)})
headers = data["headers"]
rows = data["rows"]

# Convert to typed arrays
numeric_headers = []
for col_idx, h in enumerate(headers):
    try:
        for row in rows:
            if col_idx < len(row):
                float(str(row[col_idx]))
        numeric_headers.append(h)
    except (ValueError, TypeError):
        pass

cat_headers = [h for h in headers if h not in numeric_headers]

numeric_col_indices = [headers.index(h) for h in numeric_headers]
cat_col_indices = [headers.index(h) for h in cat_headers]

fig = None

if "{chart_type}" == "bar":
    if cat_col_indices and numeric_col_indices:
        cat_col = cat_col_indices[0]
        num_col = numeric_col_indices[0]
        cat_vals = [str(row[cat_col]) if cat_col < len(row) else "" for row in rows]
        num_vals = [float(row[num_col]) if num_col < len(row) else 0 for row in rows]
        fig = go.Figure([go.Bar(x=cat_vals, y=num_vals, marker_color="#6366f1")])

elif "{chart_type}" == "line":
    if cat_col_indices and numeric_col_indices:
        cat_col = cat_col_indices[0]
        num_col = numeric_col_indices[0]
        cat_vals = [str(row[cat_col]) if cat_col < len(row) else "" for row in rows]
        num_vals = [float(row[num_col]) if num_col < len(row) else 0 for row in rows]
        fig = go.Figure([go.Scatter(x=cat_vals, y=num_vals, mode="lines+markers", line=dict(color="#6366f1"))])

elif "{chart_type}" == "scatter":
    if len(numeric_col_indices) >= 2:
        x_col, y_col = numeric_col_indices[0], numeric_col_indices[1]
        x_vals = [float(row[x_col]) if x_col < len(row) else 0 for row in rows]
        y_vals = [float(row[y_col]) if y_col < len(row) else 0 for row in rows]
        fig = go.Figure([go.Scatter(x=x_vals, y=y_vals, mode="markers", marker=dict(color="#a855f7", size=10))])

if fig is None:
    cat_vals = [str(row[0]) if row else "" for row in rows]
    num_vals = [float(row[1]) if len(row) > 1 else 0 for row in rows]
    fig = go.Figure([go.Bar(x=cat_vals, y=num_vals, marker_color="#6366f1")])

fig.update_layout(
    title="{title}",
    template="plotly_dark",
    autosize=True,
    margin=dict(l=20, r=20, t=40, b=20),
    paper_bgcolor="#1e1e2e",
    plot_bgcolor="#1e1e2e",
    font=dict(color="#cdd6f4"),
)

chart_id = "{chart_id}"
html_path = Path("chart_{chart_id}.html")
png_path = Path("chart_{chart_id}.png")

fig.write_html(str(html_path))
fig.write_image(str(png_path), engine="kaleido")

print(f"CHART_GENERATED:chart_{{chart_id}}.html")
print(f"CHART_PNG_GENERATED:chart_{{chart_id}}.png")
print(f"图表「{title}」已生成: chart_{{chart_id}}.html")
'''
    return code


@tool
def generate_chart(data: str, title: str = "数据分析图表", chart_type: str = "auto") -> str:
    """
    根据输入数据生成 Plotly 交互式图表。

    适用场景:
    - 数据可视化分析
    - 趋势图、柱状图、散点图生成
    - 分析报告中的图表素材

    Args:
        data: 数据输入,支持以下格式:
              - JSON 二维数组: '[["月份","销售额"],["1月",100],["2月",150]]'
              - JSON 对象数组: '[{"name":"A","value":10},{"name":"B","value":20}]'
              - CSV 文本: 'name,value\\nA,10\\nB,20'
        title: 图表标题
        chart_type: 图表类型,可选: auto (自动推荐) / bar / line / scatter / pie
    """
    try:
        parsed, data_format = _parse_data(data)
    except ValueError as e:
        return f"Chart generation error: {str(e)}"

    headers = parsed["headers"]
    rows = parsed["rows"]

    if chart_type == "auto":
        chart_type = _smart_chart_type(headers, rows)

    code = _generate_chart_code(chart_type, headers, rows, title)

    return (
        f"图表类型: {chart_type} | 数据: {len(rows)} 行 x {len(headers)} 列\n\n"
        f"<chart_code>\n{code}\n</chart_code>\n\n"
        f"请执行以上代码生成图表。"
    )


CHART_TOOLS = [generate_chart]
