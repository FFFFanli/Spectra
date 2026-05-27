"""
DuckDB 数据查询工具 —— 让 Agent 能直接查看和查询本地数据。

安全约束：工具受 request_context 中的 table_scope 限制。
只有当 scope 为 None（未激活）时才允许自由访问所有表；
scope 激活后，list_tables 只返回 scope 内的表，query_duckdb 拒绝 scope 外的表。
"""

from __future__ import annotations

import re

from langchain_core.tools import tool

from backend.app_paths import DUCKDB_PATH
from backend.request_context import get_table_scope

# 禁止查询的系统表 / 函数（无论 scope 是否激活）
_BLOCKED_SYSTEM_PATTERNS = [
    r"\binformation_schema\b",
    r"\bduckdb_tables\s*\(",
    r"\bduckdb_columns\s*\(",
    r"\bduckdb_databases\s*\(",
    r"\bduckdb_schemas\s*\(",
    r"\bduckdb_functions\s*\(",
    r"\bduckdb_settings\s*\(",
    r"\bpg_catalog\b",
    r"\bsqlite_master\b",
]


def _extract_table_names(sql: str) -> set[str]:
    """从 SQL 中尽可能提取被引用的表名。

    这是一个 best-effort 提取器，覆盖常见模式：
      FROM / JOIN / DESCRIBE / SHOW 后的标识符。
    不解析子查询别名（太复杂），对无法确定的场景保守放行。
    """
    # 移除单引号字符串和双引号标识符内容，简化解析
    cleaned = re.sub(r"'(?:[^']|'')*'", "''", sql)
    cleaned = re.sub(r'"(?:[^"]|"")*"', '""', cleaned)
    # 移除注释
    cleaned = re.sub(r"--[^\n]*", "", cleaned)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)

    tables: set[str] = set()

    # FROM / JOIN / TABLE / UPDATE / INSERT INTO / DESCRIBE / SHOW
    patterns = [
        r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bTABLE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bDESCRIBE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bSHOW\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
        r"\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
    ]
    for pat in patterns:
        for match in re.findall(pat, cleaned, re.IGNORECASE):
            name = match.lower()
            if name not in ("select", "where", "group", "order", "limit", "having",
                            "union", "except", "intersect", "as", "on", "set", "values",
                            "left", "right", "inner", "outer", "cross", "full", "natural",
                            "primary", "foreign", "create", "alter", "drop", "index",
                            "if", "exists", "not", "null", "default", "unique", "check",
                            "references", "cascade", "distinct", "all", "case", "when",
                            "then", "else", "end", "asc", "desc", "nulls", "first", "last"):
                tables.add(name)

    return tables


def _check_system_blocked(sql: str) -> str | None:
    """检查 SQL 是否命中禁止的系统表/函数。返回错误消息或 None。"""
    sql_lower = sql.lower()
    for pat in _BLOCKED_SYSTEM_PATTERNS:
        if re.search(pat, sql_lower):
            return f"错误: 禁止查询系统表/函数 (匹配: {pat})"
    return None


@tool
def list_tables(query: str = "") -> str:
    """列出 DuckDB 中所有可用的数据表及其结构信息。query 参数可选，用于过滤表名。

    注意：你只能看到当前请求范围内被明确授权的表。如需访问更多表，请让用户在前端附件面板中添加。
    """
    try:
        import duckdb

        scope = get_table_scope()
        conn = duckdb.connect(str(DUCKDB_PATH))

        # 获取所有用户表
        all_tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        ).fetchall()

        if not all_tables:
            conn.close()
            return "当前数据库中没有用户数据表。"

        # 如果 scope 已激活，过滤到 scope 内的表
        if scope is not None:
            allowed = {t.lower() for t in scope}
            all_tables = [(tname,) for (tname,) in all_tables if tname.lower() in allowed]

            if not all_tables:
                conn.close()
                scoped_names = ", ".join(sorted(scope))
                return (
                    f"当前请求仅授权访问以下表: {scoped_names}\n"
                    "但这些表在数据库中不存在。请确认文件已上传。"
                )

        query_lower = (query or "").strip().lower()
        lines = []
        for (tname,) in all_tables:
            if query_lower and query_lower not in tname.lower():
                continue
            try:
                cols = conn.execute(f'DESCRIBE "{tname}"').fetchall()
                col_info = ", ".join([f"{c[0]} ({c[1]})" for c in cols])
                row_count = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
                lines.append(f"- {tname}: {row_count} 行, 列: {col_info}")
            except Exception:
                lines.append(f"- {tname}")
        conn.close()

        if not lines:
            if scope is not None:
                scoped_names = ", ".join(sorted(scope))
                return f"在授权表 ({scoped_names}) 中未找到匹配 '{query}' 的表。"
            return "未找到匹配的表。"
        return "\n".join(lines)
    except Exception as e:
        return f"获取表列表失败: {e}"


@tool
def query_duckdb(sql: str) -> str:
    """在本地 DuckDB 中执行 SQL 查询并返回结果。仅支持 SELECT/DESCRIBE/SHOW 查询。

    参数 sql: 要执行的 SQL 语句。

    安全限制：
    - 禁止查询系统表 (information_schema, duckdb_*, pg_catalog 等)
    - 只能查询当前请求授权范围内的表
    """
    if not sql or not sql.strip():
        return "错误: SQL 查询不能为空"

    sql_upper = sql.strip().upper()
    allowed = ("SELECT", "DESCRIBE", "SHOW", "PRAGMA")
    if not any(sql_upper.startswith(p) for p in allowed):
        return f"错误: 仅支持 {'/'.join(allowed)} 查询，不允许修改操作"

    # 检查系统表
    blocked = _check_system_blocked(sql)
    if blocked:
        return blocked

    # 检查 scope
    scope = get_table_scope()
    if scope is not None:
        referenced = _extract_table_names(sql)
        if referenced:
            scope_lower = {t.lower() for t in scope}
            out_of_scope = referenced - scope_lower
            if out_of_scope:
                return (
                    f"错误: 查询引用了未授权的表: {', '.join(sorted(out_of_scope))}。"
                    f"当前授权表: {', '.join(sorted(scope))}。"
                    f"如需访问更多表，请在前端附件面板中添加。"
                )

    try:
        import duckdb

        conn = duckdb.connect(str(DUCKDB_PATH))
        result = conn.execute(sql).fetchall()
        columns = [desc[0] for desc in conn.description] if conn.description else []
        conn.close()

        if not columns:
            return "查询执行成功，无返回结果。"

        lines = [" | ".join(columns), "-" * 60]
        for row in result[:100]:
            lines.append(" | ".join(str(v)[:200] for v in row))
        if len(result) > 100:
            lines.append(f"... (共 {len(result)} 行，仅显示前 100 行)")
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


DUCKDB_TOOLS = [list_tables, query_duckdb]
