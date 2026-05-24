"""
DuckDB 数据查询工具 —— 让 Solo Agent 能直接查看和查询本地数据。
"""

from __future__ import annotations

from langchain_core.tools import tool

from backend.app_paths import DUCKDB_PATH


@tool
def list_tables(query: str = "") -> str:
    """列出 DuckDB 中所有可用的数据表及其结构信息。query 参数可选，用于过滤表名。"""
    try:
        import duckdb

        conn = duckdb.connect(str(DUCKDB_PATH))
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='main' ORDER BY table_name"
        ).fetchall()
        if not tables:
            conn.close()
            return "当前数据库中没有用户数据表。"

        query_lower = (query or "").strip().lower()
        lines = []
        for (tname,) in tables:
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
            return "未找到匹配的表。"
        return "\n".join(lines)
    except Exception as e:
        return f"获取表列表失败: {e}"


@tool
def query_duckdb(sql: str) -> str:
    """在本地 DuckDB 中执行 SQL 查询并返回结果。仅支持 SELECT/DESCRIBE/SHOW 查询。
    参数 sql: 要执行的 SQL 语句。"""
    if not sql or not sql.strip():
        return "错误: SQL 查询不能为空"

    sql_upper = sql.strip().upper()
    allowed = ("SELECT", "DESCRIBE", "SHOW", "PRAGMA")
    if not any(sql_upper.startswith(p) for p in allowed):
        return f"错误: 仅支持 {'/'.join(allowed)} 查询，不允许修改操作"

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
