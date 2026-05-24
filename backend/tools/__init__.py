from backend.tools.web_search import ALL_TOOLS as WEB_SEARCH_TOOLS
from backend.tools.calculator import CALCULATOR_TOOLS
from backend.tools.visualization import CHART_TOOLS
from backend.tools.sandbox import SANDBOX_TOOLS
from backend.tools.export_conversation import EXPORT_TOOLS, generate_docx
from backend.tools.duckdb_tools import DUCKDB_TOOLS
from backend.tools.heavy_tools import HEAVY_TOOLS
from backend.tools.task_manager import TASK_TOOLS
from backend.tools.knowledge_base import KNOWLEDGE_BASE_TOOLS
from backend.tools.user_memory import USER_MEMORY_TOOLS
from backend.tools.cron_manager import CRON_TOOLS
from backend.tools.user_interaction import USER_INTERACTION_TOOLS

# 统一工具面板：任务管理 + 搜索 + 计算 + 图表 + 沙盒 + DuckDB + 重型工具 + 导出 + 知识库 + 记忆 + 定时任务 + 用户交互
# 注意：TASK_TOOLS 替代了原来的 PLANNING_TOOLS（session-only → 持久化）
ALL_TOOLS = (
    TASK_TOOLS
    + WEB_SEARCH_TOOLS
    + CALCULATOR_TOOLS
    + CHART_TOOLS
    + SANDBOX_TOOLS
    + DUCKDB_TOOLS
    + HEAVY_TOOLS
    + [generate_docx]
    + KNOWLEDGE_BASE_TOOLS
    + USER_MEMORY_TOOLS
    + CRON_TOOLS
    + USER_INTERACTION_TOOLS
)

# 保留完整列表供其他模块使用
ALL_TOOLS_WITH_EXPORT = ALL_TOOLS + EXPORT_TOOLS
