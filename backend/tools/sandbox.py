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

# E2B 沙盒生命周期超时（秒）：默认 30 分钟。
# 每次 run_code 之前会调 set_timeout 续期，避免长任务（report 写作 / 搜索调研）跑到一半 sandbox 被回收。
# E2B SDK 默认只有 300s，远低于 deepseek-thinking + executor + validator + fixer 的总耗时。
def _e2b_timeout() -> int:
    try:
        return int(os.environ.get("SPECTRA_E2B_TIMEOUT", "1800"))
    except (TypeError, ValueError):
        return 1800

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

    健壮性：E2B sandbox 偶发 "running but port is not open" (502) ——
    底层 envd daemon 进程被卡死或崩溃，但容器还在。本类在 run_code 撞 502 时
    自动 kill + recreate sandbox 并重传所有文件，最多重试 MAX_E2B_RETRY 次，
    对调用方透明。
    """

    # 撞 502 / port-not-open 后允许重建 sandbox 重试的次数
    MAX_E2B_RETRY = 2
    # 哪些错误关键词判定为 sandbox 已死、需要重建
    _DEAD_SANDBOX_PATTERNS = (
        "port is not open",
        "502",
        "503",
        "504",
        "connection refused",
        "connection reset",
        "remote end closed",
        "sandbox not found",
        "sandbox is not running",
        "ServerNotReachable",
    )

    def __init__(self):
        self._e2b = None
        self._local_dir: Path | None = None
        self._backend: str | None = None
        self._uploaded: set[str] = set()
        self._closed = False
        # 缓存重建 sandbox 用的参数
        self._e2b_template: str | None = None
        self._e2b_api_key: str | None = None

    def __enter__(self):
        self._closed = False
        e2b_key = os.environ.get("E2B_API_KEY", "") if _LOCAL_EXEC_ALLOWED else ""

        if e2b_key:
            template = os.environ.get("E2B_TEMPLATE_ID", "code-interpreter-v1")
            self._e2b_api_key = e2b_key
            self._e2b_template = template
            self._create_e2b_sandbox()
            self._backend = "e2b"
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

    def _create_e2b_sandbox(self) -> None:
        """新建一个 E2B sandbox 并缓存到 self._e2b。"""
        from e2b_code_interpreter import Sandbox as E2BSandbox
        timeout = _e2b_timeout()
        self._e2b = E2BSandbox.create(
            api_key=self._e2b_api_key,
            template=self._e2b_template,
            timeout=timeout,
        )
        # 重建后必须重传文件，清空缓存
        self._uploaded.clear()
        print(
            f"[SandboxSession] E2B sandbox created "
            f"(template={self._e2b_template}, timeout={timeout}s)"
        )

    @classmethod
    def _is_dead_sandbox_error(cls, exc: BaseException) -> bool:
        """判断异常消息是否对应"sandbox 已死、应重建"。"""
        msg = (str(exc) or "").lower()
        for pat in cls._DEAD_SANDBOX_PATTERNS:
            if pat.lower() in msg:
                return True
        return False

    def _recycle_e2b_sandbox(self, reason: str) -> None:
        """kill 当前损坏的 sandbox 并立即起一个新的，重传所有已上传过的文件。"""
        print(f"[SandboxSession] recycling E2B sandbox (reason: {reason})")
        if self._e2b is not None:
            try:
                self._e2b.kill()
            except Exception as exc:
                print(f"[SandboxSession] kill broken sandbox failed (ignored): {exc}")
            self._e2b = None
        self._create_e2b_sandbox()
        # 重传 duckdb / search_service / 附带图表
        if DUCKDB_PATH.exists():
            self._ensure_file("data.duckdb", DUCKDB_PATH)
        self._ensure_file("search_service.py", SEARCH_SERVICE_PATH)
        try:
            from backend.request_context import get_attached_charts
            for chart in get_attached_charts():
                name = (chart or {}).get("name") or ""
                png_bytes = (chart or {}).get("png_bytes")
                if name and png_bytes:
                    self._e2b.files.write(name, png_bytes)
        except Exception:
            pass

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
        """跑一段代码，撞 502 / 死 sandbox 时自动重建并重试。"""
        last_exc: Exception | None = None
        for attempt in range(self.MAX_E2B_RETRY + 1):
            # 续期 sandbox：每次 run_code 前把超时窗口重置回完整的 _e2b_timeout()
            try:
                self._e2b.set_timeout(_e2b_timeout())
            except Exception as exc:
                # set_timeout 失败本身就是 sandbox 死了的信号
                if self._is_dead_sandbox_error(exc) and attempt < self.MAX_E2B_RETRY:
                    self._recycle_e2b_sandbox(f"set_timeout failed: {exc}")
                    last_exc = exc
                    continue
                print(f"[SandboxSession] E2B set_timeout error (ignored): {exc}")

            try:
                execution = self._e2b.run_code(code)
            except Exception as exc:
                last_exc = exc
                if self._is_dead_sandbox_error(exc) and attempt < self.MAX_E2B_RETRY:
                    self._recycle_e2b_sandbox(f"run_code raised: {exc}")
                    # 文件已经在 _recycle 里重传过；duckdb 如果还需要会被 _ensure_file 跳过
                    if _needs_duckdb(code):
                        self._ensure_file("data.duckdb", DUCKDB_PATH)
                    continue
                # 不是 dead sandbox 的错误，往上抛由调用方决定（fallback 到本地）
                raise

            # 成功跑到这里，处理结果
            stdout_text = "".join(execution.logs.stdout) if execution.logs.stdout else ""
            stderr_text = "".join(execution.logs.stderr) if execution.logs.stderr else ""
            error_text = ""
            if execution.error:
                error_text = f"{execution.error.name}: {execution.error.value}"
            try:
                normalized_stdout, artifacts = _harvest_e2b_artifacts(self._e2b, stdout_text)
            except Exception as exc:
                # 产物拉取阶段也可能撞 502
                if self._is_dead_sandbox_error(exc) and attempt < self.MAX_E2B_RETRY:
                    self._recycle_e2b_sandbox(f"harvest_artifacts failed: {exc}")
                    last_exc = exc
                    continue
                raise
            return {
                "ok": not execution.error,
                "stdout": normalized_stdout[:8000],
                "stderr": stderr_text[:2000],
                "error": error_text[:1000],
                "backend": "e2b",
                "artifacts": artifacts,
            }

        # 所有重试都失败：把最后一个异常往上抛，让上层 fallback 到本地
        raise last_exc if last_exc else RuntimeError("E2B sandbox retry budget exhausted")

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
    """E2B 远程沙盒执行（带 dead-sandbox 重建重试）。"""
    from e2b_code_interpreter import Sandbox

    e2b_api_key = os.environ.get("E2B_API_KEY", "")
    if not e2b_api_key:
        return None  # 回退到本地

    template_id = os.environ.get("E2B_TEMPLATE_ID", "code-interpreter-v1")
    max_retry = SandboxSession.MAX_E2B_RETRY
    last_err: str | None = None
    for attempt in range(max_retry + 1):
        try:
            with Sandbox.create(
                api_key=e2b_api_key,
                template=template_id,
                timeout=_e2b_timeout(),
            ) as sandbox:
                if DUCKDB_PATH.exists():
                    sandbox.files.write("data.duckdb", DUCKDB_PATH.read_bytes())
                if SEARCH_SERVICE_PATH.exists():
                    sandbox.files.write("search_service.py", SEARCH_SERVICE_PATH.read_bytes())

                # 把请求附带的图表 PNG 写进沙盒根目录
                try:
                    from backend.request_context import get_attached_charts
                    for chart in get_attached_charts():
                        name = (chart or {}).get("name") or ""
                        png_bytes = (chart or {}).get("png_bytes")
                        if name and png_bytes:
                            sandbox.files.write(name, png_bytes)
                except Exception:
                    pass

                execution = sandbox.run_code(code)
                stdout_text = "".join(execution.logs.stdout) if execution.logs.stdout else ""
                stderr_text = "".join(execution.logs.stderr) if execution.logs.stderr else ""
                error_text = ""
                if execution.error:
                    error_text = f"{execution.error.name}: {execution.error.value}"

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
            last_err = str(e)
            if SandboxSession._is_dead_sandbox_error(e) and attempt < max_retry:
                print(f"[_run_code_e2b] sandbox 撞 502/dead，第 {attempt + 1} 次重建并重试: {e}")
                continue
            return {"ok": False, "stdout": "", "stderr": f"E2B sandbox error: {last_err}",
                    "backend": "e2b_error", "artifacts": []}

    return {"ok": False, "stdout": "", "stderr": f"E2B sandbox retry exhausted: {last_err}",
            "backend": "e2b_error", "artifacts": []}


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
    - 数据分析和数据处理 (使用 pandas, numpy 等)
    - 生成图表 (使用 plotly, 输出 CHART_GENERATED:xxx.html 和 CHART_PNG_GENERATED:xxx.png)
    - 生成 PDF 报告 (使用 reportlab, 输出 REPORT_GENERATED:xxx.pdf)
    - 文件处理和格式转换
    - 科学计算和统计建模

    可用库: pandas, numpy, duckdb, plotly, scikit-learn, statsmodels, openpyxl, kaleido, reportlab, pypdf, pdfplumber

    【数据访问规则 —— 必须遵守】
    - 禁止使用 os.listdir / os.walk / os.scandir / glob.glob / Path.glob / Path.rglob 浏览文件系统
    - 禁止使用 duckdb 直接连接 data.duckdb 查询表列表或系统表
    - 如需查询数据，请使用 list_tables 和 query_duckdb 工具，不要通过沙盒代码绕开
    - 只能访问用户已在附件面板中明确提供的文件和数据表

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
    forbidden = [
        r"!\s*pip\s+install", r"pip\s+install",
        r"subprocess\.(run|call|Popen)", r"os\.system",
        # 文件系统探索
        r"\bos\.listdir\b", r"\bos\.walk\b", r"\bos\.scandir\b",
        r"\bglob\.glob\b", r"\.glob\s*\([\"\']", r"\.rglob\s*\(",
        # DuckDB 系统表探索
        r"information_schema\s*\.\s*tables", r"information_schema\s*\.\s*columns",
        r"\bduckdb_tables\s*\(", r"\bduckdb_columns\s*\(", r"\bduckdb_databases\s*\(",
        r"\bpg_catalog\b", r"\bsqlite_master\b",
    ]
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
