"""
E2B v2 构建脚本 — 使用程序化 API 构建自定义沙箱模板

用法:
    python build_template.py

前置条件:
    pip install e2b python-dotenv
    .env 文件中已配置 E2B_API_KEY
"""
import os
from pathlib import Path

# 自动加载项目根目录的 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"[dotenv] 已加载: {env_path}")
except ImportError:
    print("[dotenv] python-dotenv 未安装，跳过 .env 加载")

from e2b import Template


def build():
    template = (
        Template()
        .from_python_image("3.11")
        .run_cmd(
            "pip install --no-cache-dir "
            "pandas numpy duckdb plotly kaleido "
            "scikit-learn statsmodels scipy openpyxl "
            "matplotlib seaborn xlsxwriter tabulate "
            "reportlab python-docx weasyprint pypdf pdfplumber"
        )
    )

    print("Starting build for 'langgraph-data-analysis' ...")
    print("(Monitor progress at https://e2b.dev/dashboard → Templates)")

    info = Template.build(
        template,
        name="langgraph-data-analysis",
        cpu_count=2,
        memory_mb=1024,
    )

    print(f"\nBuild completed!")
    print(f"  Template name: {info.name}")
    print(f"")
    print(f"  Add this to your .env file:")
    print(f'  E2B_TEMPLATE_ID="langgraph-data-analysis"')
    print(f"  然后重启后端服务，使新的模板配置生效。")


if __name__ == "__main__":
    build()
