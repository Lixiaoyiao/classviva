"""AI 解题引擎 - 调用 DeepSeek API 批量求解数学题"""

import json
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from formatter import format_answer
from prompts import TEXT_SYSTEM_PROMPT

SYSTEM_PROMPT = TEXT_SYSTEM_PROMPT


def solve_group(qnum: int, text: str, slot_count: int, slots: list[dict] | None = None) -> dict:
    """求解一道大题的所有空，返回 {success, answers: [...]}"""
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    slot_info = _format_slot_info(slots or [])
    user_msg = f"题目：{text}\n\n空位信息：\n{slot_info}\n\n请输出 {slot_count} 个答案的 JSON 数组。"

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        raw = response.choices[0].message.content or ""
    except Exception as e:
        return {"success": False, "answers": [], "error": str(e), "raw": ""}

    # 解析 JSON
    answers = _parse_json_list(raw)

    # 如果解析失败，尝试修复
    if answers is None:
        answers = _try_fix_and_parse(raw, slot_count)

    if answers is None or len(answers) < slot_count:
        partial = [format_answer(a) for a in (answers or [])]
        error = "模型返回空内容，未生成答案" if not raw.strip() else "JSON 解析失败或答案数量不足"
        return {
            "success": False,
            "answers": partial,
            "error": error,
            "raw": raw,
        }

    # 格式化每个答案
    formatted = [format_answer(a) for a in answers[:slot_count]]
    return {"success": True, "answers": formatted, "raw": raw}


def _parse_json_list(raw: str) -> list | None:
    """从 AI 回复中提取 JSON 数组"""
    # 尝试直接解析
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试匹配 ```json [...] ``` 代码块
    import re
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试匹配裸数组
    m = re.search(r"\[.*?\]", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _try_fix_and_parse(raw: str, expected_count: int) -> list | None:
    """尝试修复常见的 JSON 格式问题"""
    import re

    # 逐行提取被引号包裹的值
    lines = raw.strip().split("\n")
    items = []
    for line in lines:
        line = line.strip().strip(",").strip()
        # 匹配 "xxx" 或 'xxx'
        m = re.match(r"""["'](.+?)["']\s*[,]?\s*$""", line)
        if m:
            items.append(m.group(1))
        # 匹配 1. "xxx" 格式
        m = re.match(r"""\d+[\.\)]\s*["'](.+?)["']""", line)
        if m:
            items.append(m.group(1))

    if len(items) >= expected_count:
        return items[:expected_count]
    return None


def solve_all(groups: list[dict]) -> list[dict]:
    """求解所有题目组，返回带结果的列表"""
    results = []
    for g in groups:
        qnum = g["qnum"]
        text = g["text"]
        slot_count = len(g["slots"])
        print(f"  [{qnum}/{len(groups)}] 求解第{qnum}题（{slot_count}个空）...")
        print(f"       题目: {text[:100]}...")

        solved = solve_group(qnum, text, slot_count, g.get("slots", []))
        solved["group"] = g
        results.append(solved)

        if solved["success"]:
            print(f"       答案: {solved['answers']}")
        else:
            print(f"       失败: {solved.get('error', '未知')}")
            if solved.get("raw"):
                print(f"       AI回复: {solved['raw'][:200]}")

    return results


def _format_slot_info(slots: list[dict]) -> str:
    if not slots:
        return "无"
    lines = []
    for index, slot in enumerate(slots, start=1):
        parts = [f"{index}. type={slot.get('input_type', 'text')}"]
        values = slot.get("radio_values") or []
        options = slot.get("options") or []
        if values:
            parts.append(f"values={values}")
        if options:
            parts.append(f"options={options}")
        lines.append(" ".join(parts))
    return "\n".join(lines)
