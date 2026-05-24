import contextlib
import io
import json
import os
import re
import sys
import traceback
from pathlib import Path

# ── 沙盒安全：禁止导入的高危模块 ──
_SANDBOX_BLOCKED_MODULES = frozenset({
    'subprocess', 'shutil', 'socket', 'ctypes', 'multiprocessing',
    'signal', 'pty', 'fcntl', 'telnetlib', 'smtplib', 'ftplib',
    'http.server', 'xmlrpc', 'pickle', 'shelve', 'asyncio.subprocess',
})

# 高危代码模式检查（正则 + 违规描述）
_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    (r'os\.(system|popen|spawn[lvpe]*|execl[pv]?|execv[pe]?)\s*\(', 'os.{func}() 被禁止'),
    (r'subprocess\.(run|call|Popen|check_output|check_call)\s*\(', 'subprocess.{func}() 被禁止'),
    (r'pip\s+install', 'pip install 被禁止'),
    (r'__import__\s*\(', '__import__() 动态导入被禁止'),
    (r'(?<!\w)eval\s*\(', 'eval() 被禁止'),
    (r'(?<!\w)exec\s*\(', 'exec() 被禁止'),
    (r'(?<!\w)compile\s*\(', 'compile() 被禁止'),
    (r'\bctypes\.', 'ctypes 调用被禁止'),
    (r'shutil\.(rmtree|copy|move|copytree)\s*\(', 'shutil.{func}() 被禁止'),
    (r'socket\.(socket|connect|bind|listen|accept)\s*\(', 'socket 网络操作被禁止'),
    (r'pickle\.(load|loads|Unpickler)\s*\(', 'pickle 反序列化被禁止'),
    (r'os\.(remove|unlink|rmdir|chmod|chown|kill)\s*\(', 'os.{func}() 被禁止'),
]

# 系统路径访问禁止
_SYSTEM_PATH_RE = re.compile(
    r'(?:["\'])(?:/etc/|/proc/|/sys/|/dev/|C:\\\Windows|C:/Windows|/System32|/systemd)',
    re.IGNORECASE,
)


def _scan_dangerous_patterns(source: str) -> list[str]:
    """扫描源代码中的高危模式，返回违规描述列表。"""
    violations: list[str] = []
    for pattern, msg_tpl in _DANGEROUS_PATTERNS:
        for m in re.finditer(pattern, source, re.IGNORECASE):
            func = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
            violations.append(msg_tpl.format(func=func))
    if _SYSTEM_PATH_RE.search(source):
        violations.append("系统路径访问被禁止 (/etc, /proc, /sys, C:\\Windows 等)")
    return violations


def _restricted_import(name, *args, **kwargs):
    """受限 __import__：阻止导入高危模块。"""
    base = name.split('.')[0]
    if base in _SANDBOX_BLOCKED_MODULES:
        raise ImportError(f"模块 '{name}' 在沙盒中被禁止导入")
    return __import__(name, *args, **kwargs)


def _restricted_eval(*_args, **_kwargs):
    raise RuntimeError("eval() 在沙盒中被禁止")


def _restricted_exec(*_args, **_kwargs):
    raise RuntimeError("exec() 在沙盒中被禁止")


def _collect_generated_files(work_dir: Path, ignored: set[str]) -> list[str]:
    files: list[str] = []
    for path in work_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(work_dir).as_posix()
        if rel in ignored:
            continue
        files.append(rel)
    return sorted(files)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: local_exec_runner.py <code_file> <result_file>", file=sys.stderr)
        return 2

    code_file = Path(sys.argv[1]).resolve()
    result_file = Path(sys.argv[2]).resolve()
    work_dir = code_file.parent
    ignored = {code_file.name, result_file.name}
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("PROJECT_ROOT", str(project_root))

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    traceback_text = ""
    error_type = ""
    ok = True

    try:
        source = code_file.read_text(encoding="utf-8")

        # 沙盒安全检查：扫描高危代码模式
        violations = _scan_dangerous_patterns(source)
        if violations:
            ok = False
            error_type = "SandboxViolation"
            traceback_text = "代码安全检查未通过:\n" + "\n".join(f"  - {v}" for v in violations)
            stdout_buffer.write(traceback_text)
            stderr_buffer.write(traceback_text)
        else:
            compiled = compile(source, str(code_file), "exec")
            import builtins as _blt
            safe_builtins = {k: v for k, v in _blt.__dict__.items()}
            safe_builtins['__import__'] = _restricted_import
            safe_builtins['eval'] = _restricted_eval
            safe_builtins['exec'] = _restricted_exec
            safe_builtins['compile'] = _restricted_eval
            globals_dict = {"__name__": "__main__", "__file__": str(code_file), "__builtins__": safe_builtins}
            locals_dict = globals_dict
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(compiled, globals_dict, locals_dict)
    except Exception as exc:
        ok = False
        error_type = exc.__class__.__name__
        traceback_text = traceback.format_exc()

    payload = {
        "ok": ok,
        "stdout": stdout_buffer.getvalue(),
        "stderr": stderr_buffer.getvalue(),
        "traceback": traceback_text,
        "error_type": error_type,
        "generated_files": _collect_generated_files(work_dir, ignored),
    }
    result_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
