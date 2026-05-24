"""
E2B 远程沙盒执行 LangChain Tool

特性:
  - Agent 可调用此工具在安全的远程沙盒中执行 Python 代码
  - 自动挂载 DuckDB 数据库和搜索服务
  - 捕获 stdout/stderr 和产物 (图表/文件/报告)
  - 超时保护 (默认 60 秒)
  - 当 E2B 不可用时回退到本地执行
"""

from __future__ import annotations

import ast
import os
import json
import re
import shutil
import subprocess
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from langchain_core.tools import tool

from backend.app_paths import (
    ARTIFACTS_DIR, BACKEND_DIR, DATA_DIR, DUCKDB_PATH,
    ensure_directories, artifact_relpath,
)

LOCAL_RUNNER_PATH = BACKEND_DIR / "local_exec_runner.py"
SEARCH_SERVICE_PATH = BACKEND_DIR / "search_service.py"
PROJECT_ROOT = BACKEND_DIR.parent
LOCAL_EXEC_TIMEOUT = 60
_LOCAL_EXEC_ALLOWED = os.environ.get("SPECTRA_ENV", "").lower() != "production"

_current_session: ContextVar = ContextVar("sandbox_session", default=None)


def _needs_duckdb(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "duckdb":
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "duckdb":
                return True
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "duckdb":
                return True
    return False

_CJK_FONT_HELPER_MARKER = "# CJK_FONT_RUNTIME_PATCH_V1"


def _patch_reportlab_cjk_support(code: str) -> str:
    """确保 reportlab 代码在运行时能正确加载中文字体，回退到 UnicodeCIDFont。"""
    if "reportlab" not in code or ".pdf" not in code.lower():
        return code
    if _CJK_FONT_HELPER_MARKER in code:
        return code

    patched = code
    if "from reportlab.pdfbase.cidfonts import UnicodeCIDFont" not in patched:
        if "from reportlab.pdfbase import pdfmetrics" in patched:
            patched = patched.replace(
                "from reportlab.pdfbase import pdfmetrics",
                "from reportlab.pdfbase import pdfmetrics\nfrom reportlab.pdfbase.cidfonts import UnicodeCIDFont",
                1,
            )
        else:
            patched = "from reportlab.pdfbase import pdfmetrics\nfrom reportlab.pdfbase.cidfonts import UnicodeCIDFont\n" + patched

    helper = """
# CJK_FONT_RUNTIME_PATCH_V1
def _ensure_cjk_font_runtime():
    import os

    candidates = [
        ("MicrosoftYaHei", r"C:\\Windows\\Fonts\\msyh.ttc"),
        ("MicrosoftYaHeiUI", r"C:\\Windows\\Fonts\\msyh.ttf"),
        ("SimHei", r"C:\\Windows\\Fonts\\simhei.ttf"),
        ("SimSun", r"C:\\Windows\\Fonts\\simsun.ttc"),
        ("NotoSansCJKsc", r"C:\\Windows\\Fonts\\NotoSansCJK-Regular.ttc"),
    ]
    for font_name, font_path in candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                try:
                    pdfmetrics.registerFontFamily(
                        font_name,
                        normal=font_name,
                        bold=font_name,
                        italic=font_name,
                        boldItalic=font_name,
                    )
                except Exception:
                    pass
                return font_name
            except Exception:
                continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        try:
            pdfmetrics.registerFontFamily(
                "STSong-Light",
                normal="STSong-Light",
                bold="STSong-Light",
                italic="STSong-Light",
                boldItalic="STSong-Light",
            )
        except Exception:
            pass
        return "STSong-Light"
    except Exception:
        return ""

_CJK_FONT_NAME = _ensure_cjk_font_runtime()
""".strip()

    anchor = "from reportlab.pdfbase.ttfonts import TTFont"
    if anchor in patched:
        patched = patched.replace(anchor, anchor + "\n" + helper, 1)
    else:
        patched = helper + "\n\n" + patched

    direct_replacements = [
        ('return "Helvetica"', 'return _CJK_FONT_NAME or "Helvetica"'),
        ("return 'Helvetica'", "return _CJK_FONT_NAME or 'Helvetica'"),
        ('chinese_font_name = "Helvetica"', 'chinese_font_name = _CJK_FONT_NAME or "Helvetica"'),
        ("chinese_font_name = 'Helvetica'", "chinese_font_name = _CJK_FONT_NAME or 'Helvetica'"),
        ('FONT_NAME = "Helvetica"', 'FONT_NAME = _CJK_FONT_NAME or "Helvetica"'),
        ("FONT_NAME = 'Helvetica'", "FONT_NAME = _CJK_FONT_NAME or 'Helvetica'"),
        ("('FONTNAME', (0, 0), (-1, -1), 'Helvetica')", "('FONTNAME', (0, 0), (-1, -1), _CJK_FONT_NAME or 'Helvetica')"),
        ('("FONTNAME", (0, 0), (-1, -1), "Helvetica")', '("FONTNAME", (0, 0), (-1, -1), _CJK_FONT_NAME or "Helvetica")'),
    ]
    for before, after in direct_replacements:
        patched = patched.replace(before, after)

    patched = re.sub(
        r"fontName\s*=\s*['\"]Helvetica(?:-Bold)?['\"]",
        "fontName=_CJK_FONT_NAME or 'Helvetica'",
        patched,
    )
    patched = re.sub(
        r"setFont\(\s*['\"]Helvetica(?:-Bold)?['\"]\s*,",
        "setFont(_CJK_FONT_NAME or 'Helvetica',",
        patched,
    )

    patched = re.sub(
        r'pdfmetrics\.registerFont\s*\(\s*TTFont\s*\(\s*[\'"]STSong-Light[\'"]\s*,\s*[\'"]STSong-Light[\'"]\s*\)\s*\)',
        'pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))',
        patched,
    )
    return patched


class SandboxSession:
    """Agent 调用期间复用的沙盒实例，避免每次 execute_python 都重建。

    ContextVar 驱动，每个 asyncio Task 各自独立。用法：
        with SandboxSession() as session:
            _current_session.set(session)
            # 所有 execute_python 调用自动复用此 session
    """

    def __init__(self):
        self._e2b = None
        self._local_dir: Path | None = None
        self._backend: str | None = None
        self._uploaded: set[str] = set()
        self._closed = False

    def __enter__(self):
        self._closed = False
        e2b_key = os.environ.get("E2B_API_KEY", "") if _LOCAL_EXEC_ALLOWED else ""

        if e2b_key:
            from e2b_code_interpreter import Sandbox as E2BSandbox
            template = os.environ.get("E2B_TEMPLATE_ID", "code-interpreter-v1")
            self._e2b = E2BSandbox.create(api_key=e2b_key, template=template)
            self._backend = "e2b"
            print(f"[SandboxSession] E2B sandbox created (template={template})")
        elif _LOCAL_EXEC_ALLOWED:
            ensure_directories()
            self._local_dir = DATA_DIR / "runs" / f"session_{uuid.uuid4().hex[:8]}"
            self._local_dir.mkdir(parents=True, exist_ok=True)
            self._backend = "local"
            print(f"[SandboxSession] local session dir: {self._local_dir}")
        else:
            raise RuntimeError("Sandbox not available: no E2B_API_KEY and SPECTRA_ENV=production")

        _current_session.set(self)
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._e2b:
            try:
                self._e2b.kill()
                print("[SandboxSession] E2B sandbox killed")
            except Exception as exc:
                print(f"[SandboxSession] E2B kill error (ignored): {exc}")
            self._e2b = None
        self._uploaded.clear()
        self._backend = None

    def _ensure_file(self, name: str, local_path: Path) -> bool:
        """上传文件到沙盒（仅第一次）。返回 True 表示本次执行了上传。"""
        if name in self._uploaded:
            return False
        if not local_path.exists():
            return False
        try:
            if self._backend == "e2b":
                self._e2b.files.write(name, local_path.read_bytes())
            else:
                shutil.copy2(local_path, self._local_dir / name)
            self._uploaded.add(name)
            print(f"[SandboxSession] uploaded: {name} ({local_path.stat().st_size / 1024 / 1024:.1f} MB)")
            return True
        except Exception as exc:
            print(f"[SandboxSession] upload failed for {name}: {exc}")
            return False

    def run_code(self, code: str) -> dict:
        """在复用沙盒中执行代码并返回结果。"""
        if self._closed:
            return {"ok": False, "stdout": "", "stderr": "Sandbox session already closed", "artifacts": []}

        code = _patch_reportlab_cjk_support(code)

        # 按需上传文件（仅第一次）
        if _needs_duckdb(code):
            self._ensure_file("data.duckdb", DUCKDB_PATH)
        self._ensure_file("search_service.py", SEARCH_SERVICE_PATH)

        # 注入请求附带的图表 PNG
        if self._backend == "e2b":
            try:
                from backend.request_context import get_attached_charts
                for chart in get_attached_charts():
                    name = (chart or {}).get("name") or ""
                    png_bytes = (chart or {}).get("png_bytes")
                    if name and png_bytes:
                        self._e2b.files.write(name, png_bytes)
            except Exception:
                pass

        if self._backend == "e2b":
            return self._run_e2b(code)
        else:
            return self._run_local(code)

    def _run_e2b(self, code: str) -> dict:
        execution = self._e2b.run_code(code)
        stdout_text = "".join(execution.logs.stdout) if execution.logs.stdout else ""
        stderr_text = "".join(execution.logs.stderr) if execution.logs.stderr else ""
        error_text = ""
        if execution.error:
            error_text = f"{execution.error.name}: {execution.error.value}"
        normalized_stdout, artifacts = _harvest_e2b_artifacts(self._e2b, stdout_text)
        return {
            "ok": not execution.error,
            "stdout": normalized_stdout[:8000],
            "stderr": stderr_text[:2000],
            "error": error_text[:1000],
            "backend": "e2b",
            "artifacts": artifacts,
        }

    def _run_local(self, code: str) -> dict:
        """本地子进程执行，复用 session 目录避免重复拷贝 DuckDB。"""
        if not _LOCAL_EXEC_ALLOWED:
            return {"ok": False, "stdout": "", "stderr": "本地执行不可用", "artifacts": []}

        # 每次执行给独立子目录，避免脚本文件冲突，但 DuckDB 已在父目录
        run_dir = self._local_dir / f"run_{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # symlink 方式暴露父目录的 data.duckdb（不需要拷贝）
        duckdb_link = run_dir / "data.duckdb"
        if not duckdb_link.exists() and (self._local_dir / "data.duckdb").exists():
            try:
                duckdb_link.symlink_to(self._local_dir / "data.duckdb")
            except OSError:
                shutil.copy2(self._local_dir / "data.duckdb", duckdb_link)

        search_link = run_dir / "search_service.py"
        if not search_link.exists() and (self._local_dir / "search_service.py").exists():
            try:
                search_link.symlink_to(self._local_dir / "search_service.py")
            except OSError:
                shutil.copy2(self._local_dir / "search_service.py", search_link)

        code_path = run_dir / "script.py"
        result_path = run_dir / "result.json"
        code_path.write_text(code, encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, str(LOCAL_RUNNER_PATH), str(code_path), str(result_path)],
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=LOCAL_EXEC_TIMEOUT,
                check=False,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": f"执行超时 ({LOCAL_EXEC_TIMEOUT}秒)", "artifacts": []}

        if result_path.exists():
            return json.loads(result_path.read_text(encoding="utf-8"))

        return {
            "ok": completed.returncode == 0,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "artifacts": [],
        }


def _run_code_local(code: str) -> dict:
    """本地子进程执行 Python 代码 (回退方案) —— 无 session 时的独立执行路径。"""
    if not _LOCAL_EXEC_ALLOWED:
        return {"ok": False, "stdout": "", "stderr": "生产环境不允许本地代码执行，请配置 E2B_API_KEY 以启用远程沙盒", "artifacts": []}

    ensure_directories()
    run_dir = DATA_DIR / "runs" / f"tool_{uuid.uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)

    code = _patch_reportlab_cjk_support(code)
    code_path = run_dir / "script.py"
    result_path = run_dir / "result.json"
    code_path.write_text(code, encoding="utf-8")

    if DUCKDB_PATH.exists():
        shutil.copy2(DUCKDB_PATH, run_dir / "data.duckdb")
    if SEARCH_SERVICE_PATH.exists():
        shutil.copy2(SEARCH_SERVICE_PATH, run_dir / "search_service.py")

    try:
        completed = subprocess.run(
            [sys.executable, str(LOCAL_RUNNER_PATH), str(code_path), str(result_path)],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=LOCAL_EXEC_TIMEOUT,
            check=False,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"执行超时 ({LOCAL_EXEC_TIMEOUT}秒)", "artifacts": []}

    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))

    return {
        "ok": completed.returncode == 0,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "artifacts": [],
    }


def _run_code_e2b(code: str) -> dict:
    """E2B 远程沙盒执行"""
    from e2b_code_interpreter import Sandbox

    e2b_api_key = os.environ.get("E2B_API_KEY", "")
    if not e2b_api_key:
        return None  # 回退到本地

    template_id = os.environ.get("E2B_TEMPLATE_ID", "code-interpreter-v1")
    try:
        with Sandbox.create(api_key=e2b_api_key, template=template_id) as sandbox:
            if DUCKDB_PATH.exists():
                sandbox.files.write("data.duckdb", DUCKDB_PATH.read_bytes())
            if SEARCH_SERVICE_PATH.exists():
                sandbox.files.write("search_service.py", SEARCH_SERVICE_PATH.read_bytes())

            # 把请求附带的图表 PNG 写进沙盒根目录，供 LLM 用 python-docx /
            # reportlab 直接嵌图（避免在沙盒里重画 ECharts）。
            try:
                from backend.request_context import get_attached_charts
                for chart in get_attached_charts():
                    name = (chart or {}).get("name") or ""
                    png_bytes = (chart or {}).get("png_bytes")
                    if name and png_bytes:
                        sandbox.files.write(name, png_bytes)
            except Exception:
                # 图表注入失败不应阻断代码执行
                pass

            execution = sandbox.run_code(code)
            stdout_text = "".join(execution.logs.stdout) if execution.logs.stdout else ""
            stderr_text = "".join(execution.logs.stderr) if execution.logs.stderr else ""
            error_text = ""
            if execution.error:
                error_text = f"{execution.error.name}: {execution.error.value}"

            # ── 产物拉取：在沙盒销毁前，把 stdout 中 marker 指向的文件搬到本地 ──
            normalized_stdout, artifacts = _harvest_e2b_artifacts(sandbox, stdout_text)

            return {
                "ok": not execution.error,
                "stdout": normalized_stdout[:8000],
                "stderr": stderr_text[:2000],
                "error": error_text[:1000],
                "backend": "e2b",
                "artifacts": artifacts,
            }
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": f"E2B sandbox error: {str(e)}", "backend": "e2b_error", "artifacts": []}


# 产物 marker → (本地文件名前缀, 默认后缀, 读取方式)
_ARTIFACT_MARKER_RULES: dict[str, tuple[str, str, str]] = {
    "CHART_GENERATED:": ("chart", ".html", "text"),
    "CHART_PNG_GENERATED:": ("chart", ".png", "bytes"),
    "CLEANED_DATA_GENERATED:": ("cleaned", ".xlsx", "bytes"),
    "FILE_GENERATED:": ("file", "", "bytes"),
    "REPORT_GENERATED:": ("report", "", "bytes"),
}


def _harvest_e2b_artifacts(sandbox, stdout_text: str) -> tuple[str, list[dict]]:
    """把沙盒里 marker 指向的产物文件拷到本地 ARTIFACTS_DIR。

    返回值：
        (改写后的 stdout, [{type, name, url}] 的产物清单)

    改写规则：把 `MARKER:sandbox_path` 替换成 `MARKER:<local-relative-path>`，
    便于 SSE 转译层正则识别本地路径并下发给前端。
    """
    if not stdout_text:
        return "", []

    ensure_directories()
    normalized = stdout_text
    artifacts: list[dict] = []

    for marker, (prefix, default_suffix, read_mode) in _ARTIFACT_MARKER_RULES.items():
        for raw_path in re.findall(rf"{re.escape(marker)}([^\r\n]+)", stdout_text):
            sandbox_path = raw_path.strip()
            if not sandbox_path:
                continue
            try:
                suffix = Path(sandbox_path).suffix or default_suffix
                local_name = f"{prefix}_{uuid.uuid4().hex[:8]}{suffix}"
                local_path = ARTIFACTS_DIR / local_name

                if read_mode == "text":
                    content = sandbox.files.read(sandbox_path)
                    local_path.write_text(content, encoding="utf-8")
                else:
                    content = sandbox.files.read_bytes(sandbox_path)
                    local_path.write_bytes(content)

                rel = artifact_relpath(local_path)
                normalized = normalized.replace(f"{marker}{raw_path}", f"{marker}{rel}")

                artifacts.append({
                    "type": _artifact_item_type(marker, suffix),
                    "name": Path(sandbox_path).name or local_name,
                    "url": f"/files/{rel}",
                    "marker": marker.rstrip(":"),
                })
            except Exception:
                # 文件不在沙盒里 / 读取失败 / 路径异常都跳过，不影响整体执行结果
                continue

    return normalized, artifacts


def _artifact_item_type(marker: str, suffix: str) -> str:
    suffix = (suffix or "").lower()
    if marker == "CHART_GENERATED:":
        return "chart_html"
    if marker == "CHART_PNG_GENERATED:":
        return "chart_png"
    if marker == "CLEANED_DATA_GENERATED:":
        return "cleaned_data"
    if marker == "REPORT_GENERATED:":
        if suffix == ".pdf":
            return "report_pdf"
        if suffix == ".docx":
            return "report_docx"
        return "report"
    if marker == "FILE_GENERATED:":
        if suffix in {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"}:
            return f"file_{suffix.lstrip('.')}"
        return "file"
    return "file"


@tool
def execute_python(code: str) -> str:
    """
    在安全的远程沙盒中执行 Python 代码,并返回执行结果。

    适用场景:
    - 数据分析和数据处理 (使用 pandas, duckdb, numpy 等)
    - 生成图表 (使用 plotly, 输出 CHART_GENERATED:xxx.html 和 CHART_PNG_GENERATED:xxx.png)
    - 生成 PDF 报告 (使用 reportlab, 输出 REPORT_GENERATED:xxx.pdf)
    - 文件处理和格式转换
    - 科学计算和统计建模

    可用库: pandas, numpy, duckdb, plotly, scikit-learn, statsmodels, openpyxl, kaleido, reportlab, pypdf, pdfplumber

    【重要：生成 PDF 报告时的强制要求】
    如果任务要求生成分析报告 PDF:
    1. 必须使用 reportlab 的 platypus (SimpleDocTemplate, Paragraph, Table, Image, PageBreak 等)
    2. 如果生成了图表 PNG，必须用 reportlab.platypus.Image 将图片嵌入到 PDF 对应章节，禁止只打印文字引用
    3. 中文字体: 依次尝试 C:\\Windows\\Fonts\\msyh.ttc, msyh.ttf, simhei.ttf, simsun.ttc
    4. 绝不要用纯文本 .txt 替代 PDF 输出

    注意: 不要使用 pip install, subprocess, os.system 等命令。

    Args:
        code: 可执行的 Python 代码
    """
    # 安全检查
    forbidden = [r"!\s*pip\s+install", r"pip\s+install", r"subprocess\.(run|call|Popen)", r"os\.system"]
    for pattern in forbidden:
        if re.search(pattern, code, re.IGNORECASE):
            return (
                f"Code execution rejected: 代码包含被禁止的操作 ({pattern})。"
                "请使用环境中已有的库完成任务。"
            )

    # 优先使用当前请求的复用 SandboxSession，无 session 时走独立执行路径
    session = _current_session.get()
    if session is not None:
        result = session.run_code(code)
    else:
        result = _run_code_e2b(code)
        if result is None:
            result = _run_code_local(code)

    if result.get("ok"):
        backend = result.get("backend", "local")
        stderr_part = ("错误输出:\n" + result['stderr'][:500]) if result.get('stderr') else ""
        return (
            f"✅ 代码执行成功 ({backend})\n\n"
            f"标准输出:\n{result['stdout'][:4000]}\n\n"
            f"{stderr_part}"
        )
    else:
        return (
            f"❌ 代码执行失败\n\n"
            f"标准输出:\n{result.get('stdout', '')[:2000]}\n\n"
            f"错误信息:\n{result.get('stderr', '')[:2000]}\n"
            f"{result.get('error', '')[:500]}"
        )


SANDBOX_TOOLS = [execute_python]
