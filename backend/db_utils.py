import pandas as pd
import duckdb
import os

from backend.app_paths import ARTIFACTS_DIR, DUCKDB_PATH, artifact_relpath, ensure_directories

# DuckDB 数据库文件路径
DB_PATH = str(DUCKDB_PATH)

def save_file_to_duckdb(file_obj, filename: str, table_name: str = None) -> pd.DataFrame:
    """
    读取上传的文件（CSV或Excel）并保存到 DuckDB 数据库中
    """
    ensure_directories()
    if filename.endswith(".csv"):
        df = pd.read_csv(file_obj)
    elif filename.endswith(".xlsx") or filename.endswith(".xls"):
        df = pd.read_excel(file_obj)
    else:
        raise ValueError("不支持的文件格式。仅支持 .csv 和 .xlsx")
    
    # 清理列名中的空格和特殊字符
    df.columns = df.columns.str.strip().str.replace(' ', '_').str.replace('-', '_')
    
    # 如果没有指定表名，使用去掉后缀的文件名
    if not table_name:
        table_name = os.path.splitext(filename)[0].replace(' ', '_').replace('-', '_').lower()
    
    # 使用 DuckDB 原生连接替代 SQLAlchemy 的 to_sql，避免 sqlalchemy 的 pg_catalog 报错
    # DuckDB Python 客户端支持直接在 SQL 语句中引用本地 DataFrame 变量 'df'
    with duckdb.connect(DB_PATH) as con:
        # 对表名加上双引号防止特殊字符报错
        con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM df')
        
    return df, table_name

def attach_external_database(db_type: str, connection_string: str, alias: str):
    """
    连接外部 MySQL 或 PostgreSQL 数据库，使其可以进行联邦查询
    """
    ensure_directories()
    with duckdb.connect(DB_PATH) as con:
        if db_type.lower() == "mysql":
            con.execute("INSTALL mysql;")
            con.execute("LOAD mysql;")
            con.execute(f"ATTACH '{connection_string}' AS {alias} (TYPE MYSQL);")
        elif db_type.lower() in ["postgres", "postgresql"]:
            con.execute("INSTALL postgres;")
            con.execute("LOAD postgres;")
            con.execute(f"ATTACH '{connection_string}' AS {alias} (TYPE POSTGRES);")
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")
    return alias

def generate_data_profile(table_name: str) -> dict:
    """
    自动数据洞察: 利用 DuckDB 的 SUMMARIZE 和 Plotly 生成数据体检报告
    """
    import plotly.express as px

    ensure_directories()
    report_md = f"### 📊 数据体检报告: `{table_name}`\n\n"
    charts = []
    
    try:
        with duckdb.connect(DB_PATH) as con:
            summary = con.execute(f"SUMMARIZE {table_name}").df()
            # 获取部分原始数据用于绘图，限制 5000 行
            df = con.execute(f"SELECT * FROM {table_name} LIMIT 5000").df()
            
        report_md += "| 字段名 | 类型 | 缺失率 | 唯一值预估 | 最小值 | 最大值 |\n"
        report_md += "|---|---|---|---|---|---|\n"
        
        for _, row in summary.iterrows():
            col_name = row['column_name']
            col_type = row['column_type']
            null_pct = f"{row['null_percentage']}%"
            unique = row['approx_unique']
            min_val = row['min'] if not pd.isna(row['min']) else "-"
            max_val = row['max'] if not pd.isna(row['max']) else "-"
            
            report_md += f"| {col_name} | {col_type} | {null_pct} | {unique} | {min_val} | {max_val} |\n"
            
            # 画数值类型的直方图
            if col_type in ['INTEGER', 'BIGINT', 'DOUBLE', 'FLOAT', 'DECIMAL', 'HUGEINT']:
                try:
                    fig = px.histogram(df, x=col_name, title=f"'{col_name}' 字段分布", marginal="box")
                    safe_col = "".join([c if c.isalnum() else "_" for c in col_name])
                    safe_table = "".join([c if c.isalnum() else "_" for c in table_name])
                    chart_file = ARTIFACTS_DIR / f"profile_{safe_table}_{safe_col}.html"
                    fig.write_html(chart_file)
                    charts.append(artifact_relpath(chart_file))
                except Exception as e:
                    pass
                    
        report_md += f"\n\n**💡 自动洞察完成**: 成功提取 {len(summary)} 个字段的体检数据，并生成 {len(charts)} 份数值分布图表（已推送至右侧面板）。\n"
        
        return {"report": report_md, "charts": charts}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"report": f"⚠️ 生成洞察报告失败: {str(e)}", "charts": []}

def get_all_tables() -> list:
    """获取 DuckDB 中所有用户表的表名列表"""
    ensure_directories()
    if not os.path.exists(DB_PATH):
        return []
    try:
        with duckdb.connect(DB_PATH) as con:
            df = con.execute(
                "SELECT DISTINCT table_name FROM duckdb_columns() "
                "WHERE database_name != 'system' AND schema_name = 'main'"
            ).df()
            tables = df['table_name'].tolist() if not df.empty else []
        return tables
    except Exception as e:
        print(f"获取表列表失败: {e}")
        return []


def get_table_preview(table_name: str, limit: int = 100) -> dict:
    """获取指定表的前 N 行数据，返回 {columns, rows, total_rows}"""
    ensure_directories()
    try:
        with duckdb.connect(DB_PATH) as con:
            total = con.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
            df = con.execute(f'SELECT * FROM "{table_name}" LIMIT {limit}').df()
        return {
            "columns": df.columns.tolist(),
            "rows": df.values.tolist(),
            "total_rows": total,
        }
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "total_rows": 0}


def get_scoped_database_schema(table_names: set[str] | None = None) -> str:
    """
    获取指定表的 DDL 以及前几行数据。传入 None 时等同于 get_database_schema()（返回所有表）。

    安全设计：Agent 修复器应通过此接口获取限定范围的 schema，
    而不是通过 get_database_schema() 获取全库 schema。
    """
    if table_names is None:
        return get_database_schema()

    ensure_directories()
    if not os.path.exists(DB_PATH):
        return "数据库不存在，请先上传数据文件或连接数据库。"

    if not table_names:
        return "当前请求未包含任何数据表。"

    try:
        schema_info = "【当前任务涉及的数据表】:\n\n"
        with duckdb.connect(DB_PATH) as con:
            scope_set = {t.lower() for t in table_names}
            columns_df = con.execute(
                "SELECT table_name, column_name, data_type FROM duckdb_columns() "
                "WHERE database_name != 'system'"
            ).df()

            if columns_df.empty:
                return "数据库中没有任何表。"

            grouped = columns_df.groupby("table_name")

            found_any = False
            for table, group in grouped:
                if table.lower() not in scope_set:
                    continue
                found_any = True
                display_table_name = table
                cols_desc = ",\n  ".join(
                    [f'"{row["column_name"]}" {row["data_type"]}' for _, row in group.iterrows()]
                )
                ddl = f'CREATE TABLE "{display_table_name}" (\n  {cols_desc}\n);'

                try:
                    df_sample = con.execute(
                        f'SELECT * FROM "{display_table_name}" LIMIT 3'
                    ).df()
                    sample_data_str = df_sample.to_markdown()
                except Exception:
                    sample_data_str = "(无法获取示例数据)"

                schema_info += f"--- 表名: {display_table_name} ---\n"
                schema_info += f"表结构:\n{ddl}\n\n"
                schema_info += f"数据示例 (前3行):\n{sample_data_str}\n\n"

            if not found_any:
                return f"指定的表 {', '.join(sorted(table_names))} 在数据库中不存在。"

            return schema_info
    except Exception as e:
        return f"获取数据库结构时发生错误: {str(e)}"


def get_database_schema() -> str:
    """
    获取 DuckDB 数据库中所有表的 DDL 以及前几行数据，支持多表关联分析。
    """
    ensure_directories()
    if not os.path.exists(DB_PATH):
        return "数据库不存在，请先上传数据文件或连接数据库。"
    
    try:
        schema_info = "【当前数据库中包含的表信息如下】:\n\n"
        with duckdb.connect(DB_PATH) as con:
            # 使用 duckdb_columns() 获取所有附加数据库的表结构信息，排除系统表
            columns_df = con.execute("SELECT database_name, schema_name, table_name, column_name, data_type FROM duckdb_columns() WHERE database_name != 'system'").df()
            
            if columns_df.empty:
                return "数据库中没有任何表。"
            
            # 按数据库、模式、表分组
            grouped = columns_df.groupby(['database_name', 'schema_name', 'table_name'])
            
            for (db, schema, table), group in grouped:
                full_table_name = f"{db}.{schema}.{table}" if db != "data" else table # data 是默认db，但duckdb可能是其他名，统使用 db.schema.table
                # 如果是主库，直接用表名，否则带上前缀
                display_table_name = table if db in ['memory', 'data', 'main'] else f"{db}.{table}"
                
                cols_desc = ",\n  ".join([f'"{row["column_name"]}" {row["data_type"]}' for _, row in group.iterrows()])
                ddl = f'CREATE TABLE "{display_table_name}" (\n  {cols_desc}\n);'
                
                # 获取前三行数据作为示例
                try:
                    df_sample = con.execute(f'SELECT * FROM {display_table_name} LIMIT 3').df()
                    sample_data_str = df_sample.to_markdown()
                except:
                    sample_data_str = "(无法获取示例数据)"
                
                schema_info += f"--- 表名: {display_table_name} ---\n"
                schema_info += f"表结构:\n{ddl}\n\n"
                schema_info += f"数据示例 (前3行):\n{sample_data_str}\n\n"
                
            return schema_info
    except Exception as e:
        return f"获取数据库结构时发生错误: {str(e)}"
