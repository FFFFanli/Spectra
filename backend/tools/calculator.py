"""
安全计算器 LangChain Tool —— 支持数学表达式求值

特性:
  - 使用受限的 eval 环境 (仅允许安全的内置函数)
  - 支持算术运算、三角函数、对数等
  - 结果带单位上下文
"""

import math
from langchain_core.tools import tool

SAFE_BUILTINS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "pow": pow,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "pi": math.pi,
    "e": math.e,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "gcd": math.gcd,
}


@tool
def calculator(expression: str) -> str:
    """
    安全的数学表达式求值器。
    支持算术运算、三角函数、对数、取整等常见数学运算。

    使用场景:
    - 数据分析中的数值计算
    - 统计指标的快速计算 (增长率、平均值等)
    - 财务计算 (复利、折现等)

    支持的函数: sqrt, sin, cos, tan, log, log10, log2, exp, pi, e, ceil, floor, abs, round, pow, min, max, sum

    Args:
        expression: 数学表达式, 例如 "100 * (1 + 0.05) ** 3" 或 "sqrt(144) + log10(1000)"
    """
    cleaned = expression.strip()

    # 禁止危险操作
    dangerous = ["__", "import", "exec", "eval", "compile", "open", "os.", "sys.", "subprocess", "lambda", "class"]
    lowered = cleaned.lower()
    for d in dangerous:
        if d in lowered:
            return f"Calculator error: 表达式包含禁止的关键字 '{d}'。"

    try:
        result = eval(cleaned, {"__builtins__": {}}, SAFE_BUILTINS)
        if isinstance(result, float):
            result = round(result, 10)
        return f"计算结果: {cleaned} = {result}"
    except SyntaxError as e:
        return f"Calculator error: 语法错误 - {str(e)}"
    except Exception as e:
        return f"Calculator error: {str(e)}"


@tool
def summarize_numbers(numbers: str) -> str:
    """
    对一组数字进行描述性统计分析 (计数、总和、均值、中位数、最大、最小、标准差)。

    Args:
        numbers: 逗号分隔的数字列表, 例如 "1.5, 2.3, 4.1, 5.0, 3.2"
    """
    try:
        nums = [float(x.strip()) for x in numbers.split(",") if x.strip()]
    except ValueError:
        return "Summarize error: 输入包含无法解析的数字。"

    if not nums:
        return "Summarize error: 输入为空。"

    n = len(nums)
    total = sum(nums)
    avg = total / n
    sorted_nums = sorted(nums)
    median = sorted_nums[n // 2] if n % 2 == 1 else (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2
    variance = sum((x - avg) ** 2 for x in nums) / n
    stdev = math.sqrt(variance)

    return (
        f"【描述性统计】(n={n})\n"
        f"总和: {round(total, 4)}\n"
        f"均值: {round(avg, 4)}\n"
        f"中位数: {round(median, 4)}\n"
        f"最大值: {round(max(nums), 4)}\n"
        f"最小值: {round(min(nums), 4)}\n"
        f"标准差: {round(stdev, 4)}"
    )


CALCULATOR_TOOLS = [calculator, summarize_numbers]
