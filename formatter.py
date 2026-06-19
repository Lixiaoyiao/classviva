"""答案格式化器 - 将 AI 输出的答案转换为 classviva 兼容格式"""

import re


def format_answer(raw_answer: str) -> str:
    """
    按照 classviva 数学符号规范格式化答案：
    - 全角符号 → 半角
    - 中文符号 → 英文符号
    - 清理多余空格和格式
    - 统一括号为圆括号
    """
    raw_answer = str(raw_answer)

    # 全角数字 → 半角
    fullwidth = "０１２３４５６７８９＋－×÷＝＜＞（）［］｛｝．，；：！？＾％＊＃＠＆"
    halfwidth = "0123456789+-*/=<>()[]{}.,;:!?^%*#@&"
    full_to_half = str.maketrans(fullwidth, halfwidth)
    answer = raw_answer.translate(full_to_half)

    # 中文数学符号 → 英文
    answer = answer.replace("（", "(").replace("）", ")")
    answer = answer.replace("［", "[").replace("］", "]")
    answer = answer.replace("｛", "{").replace("｝", "}")
    answer = answer.replace("＋", "+").replace("－", "-")
    answer = answer.replace("×", "*").replace("÷", "/")
    answer = answer.replace("＝", "=").replace("＞", ">").replace("＜", "<")
    answer = answer.replace("＾", "^").replace("％", "%")
    answer = answer.replace("．", ".").replace("，", ",")
    answer = answer.replace("；", ";").replace("：", ":")
    answer = answer.replace("！", "!").replace("？", "?")

    # 清理多余空格
    answer = answer.strip()
    answer = re.sub(r"\s+", " ", answer)

    # 处理常见格式
    answer = _fix_exponent(answer)
    answer = _normalize_greek(answer)
    answer = _normalize_pi(answer)
    answer = _normalize_sqrt(answer)
    answer = _normalize_superscripts(answer)
    answer = _normalize_abs(answer)
    answer = _fix_function_spacing(answer)

    return answer


def _fix_exponent(expr: str) -> str:
    """将 x^2 或 x**2 统一为 x^2"""
    expr = re.sub(r"\*{2,3}", "^", expr)
    return expr


def _normalize_pi(expr: str) -> str:
    """π → pi"""
    return expr.replace("π", "pi")


def _normalize_greek(expr: str) -> str:
    """希腊字母 → classviva 支持的英文名"""
    mapping = {
        "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta",
        "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
        "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu",
        "ν": "nu", "ξ": "xi", "ο": "omicron", "π": "pi",
        "ρ": "rho", "ς": "sigmaf", "σ": "sigma", "τ": "tau",
        "υ": "upsilon", "φ": "phi", "χ": "chi", "ψ": "psi",
        "ω": "omega", "ϑ": "thetasym", "ϒ": "upsih", "ϖ": "piv",
    }
    for source, target in mapping.items():
        expr = expr.replace(source, target)
    return expr


def _normalize_sqrt(expr: str) -> str:
    """√(expr) → sqrt(expr), √x → sqrt(x)（x 为单字母/数字）"""
    expr = re.sub(r"√\(", "sqrt(", expr)  # √( → sqrt(
    expr = re.sub(r"√([a-zA-Z0-9])", r"sqrt(\1)", expr)  # √x → sqrt(x)
    return expr


def _normalize_superscripts(expr: str) -> str:
    """²³⁴⁵⁶⁷⁸⁹⁰ → ^2 ^3 ..."""
    mapping = str.maketrans("²³⁴⁵⁶⁷⁸⁹⁰¹", "2345678901")
    result = ""
    for ch in expr:
        if ch in "²³⁴⁵⁶⁷⁸⁹⁰¹":
            result += "^" + ch.translate(mapping)
        else:
            result += ch
    return result


def _normalize_abs(expr: str) -> str:
    """∣x∣ → abs(x)（Unicode U+2223 绝对值符号，不是 ASCII |）"""
    expr = re.sub(r"∣(.+?)∣", r"abs(\1)", expr)
    return expr


def _fix_function_spacing(expr: str) -> str:
    """确保函数后有括号时格式正确，如 sin(x) 而非 sin (x)"""
    funcs = [
        "sin", "cos", "tan", "sec", "csc", "cot",
        "arcsin", "arccos", "arctan", "arcsec", "arccsc", "arccot",
        "asin", "acos", "atan", "asec", "acsc", "acot",
        "sinh", "cosh", "tanh", "sech", "csch", "coth",
        "asinh", "acosh", "atanh", "asech", "acsch", "acoth",
        "arcsinh", "arccosh", "arctanh", "arcsech", "arccsch", "arccoth",
        "log", "ln", "log10", "logten", "sqrt", "abs", "int", "sgn",
        "norm", "unit", "arg", "mod", "Re", "Im", "conj",
    ]
    for fn in funcs:
        expr = re.sub(rf"\b{fn}\s+\(", f"{fn}(", expr)
    return expr


def validate_answer(answer: str) -> bool:
    """检查答案是否只包含 classviva 允许的字符"""
    allowed = re.compile(
        r"^[\d\s+\-*/^_().,;:!?<>\[\]{}a-zA-Z]+$"
    )
    return bool(allowed.match(answer))


def extract_final_answer(ai_response: str) -> str:
    """从 AI 的完整回复中提取最终答案"""
    # 尝试匹配 "答案：xxx" 或 "答案: xxx" 或 "Answer: xxx"
    patterns = [
        r"(?:最终)?答案[：:]\s*(.+?)(?:\n|$)",
        r"(?:Final\s*)?Answer[：:\s]+(.+?)(?:\n|$)",
        r"```\s*(.+?)\s*```",  # 代码块中的内容
        r"^\s*(.+?)\s*$",     # 最后一行非空内容（兜底）
    ]
    for pat in patterns:
        m = re.search(pat, ai_response, re.MULTILINE | re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ai_response.strip()
