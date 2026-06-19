"""多模态视觉兜底。

用于图片题、图表题，或 DOM 提取质量较低的题目。
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from openai import OpenAI

import config
from formatter import format_answer
from prompts import VISION_SYSTEM_PROMPT


def vision_configured() -> bool:
    return bool(getattr(config, "VISION_API_KEY", "").strip())


def solve_page_from_image(image_bytes: bytes, groups: list[dict] | None = None) -> dict:
    """从当前页面截图识别并解题，返回统一 answers 结构。"""
    if not vision_configured():
        return {
            "success": False,
            "items": [],
            "error": "未配置 VISION_API_KEY",
            "raw": "",
        }

    expected = _expected_groups(groups or [])
    prompt = f"""{VISION_SYSTEM_PROMPT}

请从截图中读取 classviva 页面上的题目、图片、图表、公式和空位，并直接给出最终答案。

输出必须是 JSON，不要解释过程：
{{
  "items": [
    {{"qnum": 1, "answers": ["答案1"], "confidence": "high", "note": ""}}
  ]
}}

要求：
- 每道大题一个 item。
- answers 数量尽量匹配该题空位数。
- 不存在写 DNE。
- 选择题写选项字母或页面要求的 value。
- 分数写 a/b，幂写 ^，函数写 sin(x)、sqrt(x)。
- 如果看不清某题，仍返回 item，confidence 写 low，note 说明原因。

DOM 已识别到的题号、空位和质量信息：
{json.dumps(expected, ensure_ascii=False)}
"""
    raw = _call_vision_model(prompt, image_bytes)
    parsed = _parse_json_object(raw)
    items = _normalize_items((parsed or {}).get("items", []))
    return {"success": bool(items), "items": items, "raw": raw}


def solve_groups_with_vision(image_bytes: bytes, groups: list[dict]) -> list[dict]:
    """把视觉结果转换成 solver.py 风格的 results。"""
    visual = solve_page_from_image(image_bytes, groups)
    if not visual.get("success"):
        return [
            {
                "success": False,
                "answers": [],
                "error": visual.get("error", "视觉识别失败"),
                "raw": visual.get("raw", ""),
                "group": group,
                "vision": True,
            }
            for group in groups
        ]

    results = []
    for group in groups:
        item = _find_item(visual["items"], group.get("qnum"))
        if not item:
            results.append({
                "success": False,
                "answers": [],
                "error": "视觉结果未包含该题",
                "raw": visual.get("raw", ""),
                "group": group,
                "vision": True,
            })
            continue

        answers = item.get("answers", [])
        slot_count = len(group.get("slots", []))
        success = len(answers) >= slot_count if slot_count else bool(answers)
        results.append({
            "success": success,
            "answers": answers[:slot_count] if slot_count else answers,
            "raw": visual.get("raw", ""),
            "group": group,
            "vision": True,
            "confidence": item.get("confidence", "unknown"),
            "note": item.get("note", ""),
            "error": "" if success else "视觉答案数量不足",
        })
    return results


def read_questions_from_image(image_bytes: bytes, groups: list[dict]) -> dict:
    """只从截图转写题面，不求解。"""
    if not vision_configured():
        return {"success": False, "questions": {}, "error": "未配置 VISION_API_KEY", "raw": ""}

    expected = _expected_groups(groups)
    prompt = f"""请只转写截图中的数学题题面，不要解题。
输出 JSON：
{{"questions":[{{"qnum":1,"text":"完整题面文字，包含公式、图片信息、图表信息和每个小问"}}]}}

要求：
- 图片、函数图、几何图、表格要用文字描述清楚。
- 公式用普通文本或 LaTeX 均可。
- 不要加入截图里没有的解释。

DOM 已识别到的题号、空位和质量信息：
{json.dumps(expected, ensure_ascii=False)}
"""
    raw = _call_vision_model(prompt, image_bytes)
    parsed = _parse_json_object(raw)
    questions: dict[int, str] = {}
    for item in (parsed or {}).get("questions", []):
        if not isinstance(item, dict):
            continue
        qnum = _safe_int(item.get("qnum"))
        text = str(item.get("text") or "").strip()
        if qnum is not None and text:
            questions[qnum] = text
    return {"success": bool(questions), "questions": questions, "raw": raw}


def _call_vision_model(prompt: str, image_bytes: bytes) -> str:
    client = OpenAI(
        api_key=getattr(config, "VISION_API_KEY", ""),
        base_url=getattr(config, "VISION_BASE_URL", "https://api.openai.com/v1"),
    )
    model = getattr(config, "VISION_MODEL", "gpt-4o-mini")
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        temperature=0.0,
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""


def _normalize_items(items: Any) -> list[dict]:
    if not isinstance(items, list):
        return []
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        answers = item.get("answers") or []
        if not isinstance(answers, list):
            answers = [answers]
        normalized.append({
            "qnum": _safe_int(item.get("qnum")),
            "answers": [format_answer(str(answer)) for answer in answers],
            "confidence": str(item.get("confidence") or "unknown"),
            "note": str(item.get("note") or ""),
        })
    return normalized


def _parse_json_object(raw: str) -> dict | None:
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _expected_groups(groups: list[dict]) -> list[dict[str, Any]]:
    expected = []
    for group in groups:
        expected.append({
            "qnum": group.get("qnum"),
            "slot_count": len(group.get("slots", [])),
            "text": str(group.get("text") or "")[:800],
            "quality": group.get("quality", {}),
            "assets": group.get("assets", {}),
        })
    return expected


def _find_item(items: list[dict], qnum: int | None) -> dict | None:
    for item in items:
        if item.get("qnum") == qnum:
            return item
    return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
