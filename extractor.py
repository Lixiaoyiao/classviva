"""自适应题目提取器。

classviva 的不同页面可能使用不同的容器、MathJax 渲染方式和输入框结构。
这个模块尽量围绕“最终可填写的输入框”反推题目，而不是只依赖固定 class 名。
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page


NOISE_PATTERNS = [
    r"Try\s+\d+",
    r"满分[\d.]+",
    r"标记试题",
    r"试题正文",
    r"填入答案时[，,].*?输入法[。.]?",
    r"visibility\s*预览输入.*",
    r"测验导航.*",
]


def extract_question_groups(page: Page, selectors: dict[str, str], extract_wait: int = 5000) -> list[dict]:
    """提取题目、空位和质量信息。"""
    page.wait_for_timeout(extract_wait)
    slots = _extract_slots(page, selectors)
    if not slots:
        print("[提取] 未找到答案输入框")
        return []

    grouped: dict[int, dict] = {}
    for slot in slots:
        qnum = slot["qnum"]
        grouped.setdefault(qnum, {"qnum": qnum, "slots": []})
        grouped[qnum]["slots"].append(slot)

    body = get_body_with_latex(page)
    blocks = split_by_qnum(body)

    result = []
    for qnum in sorted(grouped):
        group = grouped[qnum]
        context = _context_for_group(page, group["slots"])
        text = _choose_text(
            qnum=qnum,
            context_text=context.get("text", ""),
            body_text=blocks.get(qnum, ""),
        )

        group["text"] = text
        group["slots"].sort(key=lambda item: item["subnum"])
        group["assets"] = context.get("assets", {})
        group["quality"] = score_quality(group)
        result.append(group)

    total_slots = sum(len(g["slots"]) for g in result)
    weak_count = sum(1 for g in result if g["quality"]["needs_vision"])
    print(f"[提取] {len(result)} 道大题，共 {total_slots} 个空，{weak_count} 道建议视觉兜底")
    return result


def get_body_with_latex(page: Page) -> str:
    """获取页面正文，并尽量保留 MathJax 源码。"""
    js = """
    () => {
        const clone = document.body.cloneNode(true);
        const BS = String.fromCharCode(92);

        clone.querySelectorAll('script[type*="math"]').forEach(s => {
            const tex = (s.textContent || '').trim();
            if (!tex || tex.includes('MathJax.Hub.Config') || tex.includes('MathJax.Ajax')
                || tex.includes('MathMenu') || tex.includes('MathJax.Hub.Register')) {
                s.remove(); return;
            }
            const sp = document.createElement('span');
            sp.textContent = ' $' + tex + '$ ';
            s.parentNode && s.parentNode.replaceChild(sp, s);
        });

        clone.querySelectorAll(
            'mjx-container, .MathJax_Display, .MathJax_Preview, span.MathJax, div.MathJax, ' +
            '[class*="MathJax"], [class*="mjx-"]'
        ).forEach(el => { try { el.remove(); } catch(e) {} });

        const lb1 = BS + '(';
        const rb1 = BS + ')';
        const lb2 = BS + '[';
        const rb2 = BS + ']';
        const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(n => {
            let t = n.textContent || '';
            if (t.includes(lb1)) { t = t.split(lb1).join(' $'); t = t.split(rb1).join('$ '); }
            if (t.includes(lb2)) { t = t.split(lb2).join(' $$'); t = t.split(rb2).join('$$ '); }
            n.textContent = t;
        });

        return clone.innerText || '';
    }
    """
    try:
        body = page.evaluate(js)
        if body and len(body) > 50:
            return body
    except Exception as exc:
        print(f"  [!] LaTeX 提取失败: {exc}")
    return page.inner_text("body")


def split_by_qnum(body: str) -> dict[int, str]:
    """按常见题号格式切分整页文本。"""
    result: dict[int, str] = {}
    patterns = [
        r"试题\s*(\d+)\b",
        r"题目\s*(\d+)\b",
        r"Question\s*(\d+)\b",
        r"Problem\s*(\d+)\b",
    ]
    for pattern in patterns:
        blocks = re.split(pattern, body, flags=re.IGNORECASE)
        if len(blocks) > 2:
            for i in range(1, len(blocks), 2):
                try:
                    qnum = int(blocks[i])
                except ValueError:
                    continue
                content = blocks[i + 1] if i + 1 < len(blocks) else ""
                result[qnum] = clean_text(content)[:4000]
            if result:
                break
    return result


def score_quality(group: dict) -> dict:
    """给每道题的提取结果打分，用于决定是否需要视觉兜底。"""
    text = group.get("text", "").strip()
    assets = group.get("assets", {})
    reasons = []
    score = 1.0

    if len(text) < 30:
        score -= 0.45
        reasons.append("题面过短")
    if text == f"第{group.get('qnum')}题":
        score -= 0.55
        reasons.append("只识别到题号")
    if assets.get("image_count", 0) > 0:
        score -= 0.35
        reasons.append("题目区域含图片")
    if assets.get("canvas_count", 0) > 0:
        score -= 0.35
        reasons.append("题目区域含 canvas")
    if assets.get("svg_count", 0) > 0:
        score -= 0.2
        reasons.append("题目区域含 svg")
    if assets.get("math_count", 0) == 0 and re.search(r"lim|int|sqrt|frac|sum|∫|√|π", text, re.I):
        score -= 0.1
        reasons.append("公式可能不完整")

    score = max(0.0, min(1.0, score))
    return {
        "score": round(score, 2),
        "needs_vision": score < 0.75,
        "reasons": reasons,
    }


def clean_text(text: str) -> str:
    text = text or ""
    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_slots(page: Page, selectors: dict[str, str]) -> list[dict]:
    answer_selector = selectors.get("answer_input", "input[id*='AnSwEr']")
    if "select" not in answer_selector:
        answer_selector = f"{answer_selector}, select[id*='AnSwEr'], select[name*='AnSwEr']"
    radio_selector = selectors.get(
        "radio_input",
        "input[type='radio'][id*='AnSwEr'], input[type='radio'][name*='AnSwEr'], "
        "input[type='checkbox'][id*='AnSwEr'], input[type='checkbox'][name*='AnSwEr']",
    )
    all_inputs = page.query_selector_all(f"{answer_selector}, {radio_selector}")
    answer_pattern = selectors.get("answer_id_pattern", r"q(\d+):(\d+)_AnSwEr(\d+)")

    slots = []
    seen: dict[str, dict] = {}
    fallback_qnum = 0
    qnum_counts: dict[int, int] = {}

    for index, inp in enumerate(all_inputs, start=1):
        input_id = inp.get_attribute("id") or ""
        input_name = inp.get_attribute("name") or ""
        tag_name = inp.evaluate("el => el.tagName.toLowerCase()")
        input_type = (inp.get_attribute("type") or tag_name).lower()
        input_value = inp.get_attribute("value") or ""

        if input_type == "hidden" or "previous_AnSwEr" in input_name or "previous_AnSwEr" in input_id:
            continue

        parsed = _parse_slot_numbers(input_id, input_name, answer_pattern)
        if parsed:
            qnum, subnum = parsed
            if input_type in ("radio", "checkbox") and _is_generic_choice_id(input_id, input_name):
                subnum = qnum_counts.get(qnum, 0) + 1
            qnum_counts[qnum] = max(qnum_counts.get(qnum, 0), subnum)
        else:
            qnum = _parse_question_number(input_id, input_name)
            if qnum is None:
                fallback_qnum += 1
                qnum = fallback_qnum
            subnum = qnum_counts.get(qnum, 0) + 1
            qnum_counts[qnum] = subnum

        key = input_name if input_type in ("radio", "checkbox") and input_name else input_id or input_name or f"slot-{index}"
        if key in seen:
            if input_type in ("radio", "checkbox") and input_value:
                values = seen[key].setdefault("radio_values", [])
                if input_value not in values:
                    values.append(input_value)
            continue

        slot = {
            "qnum": qnum,
            "subnum": subnum,
            "input_id": input_id,
            "input_name": input_name,
            "input_type": input_type,
            "radio_values": [input_value] if input_type in ("radio", "checkbox") and input_value else [],
            "options": _extract_options(inp) if tag_name == "select" else [],
            "selector": _selector_for_input(input_id, input_name, index),
        }
        seen[key] = slot
        slots.append(slot)

    return slots


def _parse_slot_numbers(input_id: str, input_name: str, answer_pattern: str) -> tuple[int, int] | None:
    for source in (input_id, input_name):
        if not source:
            continue
        match = re.match(answer_pattern, source)
        if match:
            return int(match.group(2)), int(match.group(3))

        numbers = [int(n) for n in re.findall(r"\d+", source)]
        if len(numbers) >= 2 and "answer" in source.lower():
            return numbers[-2], numbers[-1]
    return None


def _parse_question_number(input_id: str, input_name: str) -> int | None:
    for source in (input_id, input_name):
        if not source:
            continue
        match = re.search(r"q\d+:(\d+)", source)
        if match:
            return int(match.group(1))
    return None


def _is_generic_choice_id(input_id: str, input_name: str) -> bool:
    source = f"{input_id} {input_name}".lower()
    return "answer" in source and "answer000" not in source.lower()


def _extract_options(inp) -> list[dict]:
    try:
        return inp.evaluate(
            """el => Array.from(el.options || []).map(option => ({
                value: option.value || '',
                text: (option.textContent || '').trim()
            })).filter(option => option.value || option.text)"""
        )
    except Exception:
        return []


def _selector_for_input(input_id: str, input_name: str, index: int) -> str:
    if input_id:
        return f"#{_css_escape(input_id)}"
    if input_name:
        return f"[name='{input_name.replace(chr(39), chr(92) + chr(39))}']"
    return f"input:nth-of-type({index})"


def _context_for_group(page: Page, slots: list[dict]) -> dict[str, Any]:
    selectors = [slot["selector"] for slot in slots if slot.get("selector")]
    js = """
    (selectors) => {
        const textOf = (el) => {
            if (!el) return '';
            const clone = el.cloneNode(true);
            const BS = String.fromCharCode(92);

            clone.querySelectorAll('script[type*="math"]').forEach(s => {
                const tex = (s.textContent || '').trim();
                if (!tex || tex.includes('MathJax.Hub.Config') || tex.includes('MathJax.Ajax')
                    || tex.includes('MathMenu') || tex.includes('MathJax.Hub.Register')) {
                    s.remove(); return;
                }
                const sp = document.createElement('span');
                sp.textContent = ' $' + tex + '$ ';
                s.parentNode && s.parentNode.replaceChild(sp, s);
            });

            clone.querySelectorAll(
                'mjx-container, .MathJax_Display, .MathJax_Preview, span.MathJax, div.MathJax, ' +
                '[class*="MathJax"], [class*="mjx-"]'
            ).forEach(math => { try { math.remove(); } catch(e) {} });

            const lb1 = BS + '(';
            const rb1 = BS + ')';
            const lb2 = BS + '[';
            const rb2 = BS + ']';
            const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
            const nodes = [];
            while (walker.nextNode()) nodes.push(walker.currentNode);
            nodes.forEach(n => {
                let t = n.textContent || '';
                if (t.includes(lb1)) { t = t.split(lb1).join(' $'); t = t.split(rb1).join('$ '); }
                if (t.includes(lb2)) { t = t.split(lb2).join(' $$'); t = t.split(rb2).join('$$ '); }
                n.textContent = t;
            });

            return (clone.innerText || clone.textContent || '').trim();
        };
        const hasAnswer = (el) => el && !!el.querySelector('[id*="AnSwEr"], [name*="AnSwEr"]');
        const answerSelector = [
            'input:not([type="hidden"])[id*="AnSwEr"]',
            'input:not([type="hidden"])[name*="AnSwEr"]',
            'textarea[id*="AnSwEr"]',
            'textarea[name*="AnSwEr"]',
            'select[id*="AnSwEr"]',
            'select[name*="AnSwEr"]'
        ].join(',');
        const visibleAnswerCount = (el) => el ? Array.from(el.querySelectorAll(answerSelector)).filter(answer => {
            const rect = answer.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }).length : 0;
        const statsOf = (el) => ({
            image_count: el ? el.querySelectorAll('img').length : 0,
            canvas_count: el ? el.querySelectorAll('canvas').length : 0,
            svg_count: el ? el.querySelectorAll('svg').length : 0,
            math_count: el ? el.querySelectorAll('script[type*="math"], mjx-container, .MathJax, [class*="MathJax"]').length : 0,
            alt_texts: el ? Array.from(el.querySelectorAll('img')).map(img => img.alt || img.title || '').filter(Boolean).slice(0, 8) : []
        });
        const visibleEnough = (el) => {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };
        const candidates = [];
        for (const selector of selectors) {
            const input = document.querySelector(selector);
            if (!input) continue;
            let node = input;
            for (let depth = 0; depth < 12 && node; depth += 1) {
                const text = textOf(node);
                const stats = statsOf(node);
                if (visibleEnough(node) && hasAnswer(node) && (text.length > 20 || stats.image_count || stats.canvas_count || stats.svg_count)) {
                    const cls = node.className || '';
                    const id = node.id || '';
                    const marker =
                        /试题|Question|Problem|Try|满分|试题正文/.test(text) ||
                        /que|question|formulation|content|question-container|que/.test(String(cls) + ' ' + id);
                    const nav =
                        /测验导航|跳至\\.\\.\\.|保存答题/.test(text) ||
                        /quiz_nav|navblock|navbar|footer|breadcrumb/.test(String(cls) + ' ' + id);
                    const answerCount = visibleAnswerCount(node);
                    candidates.push({text, assets: stats, depth, marker, nav, answerCount, className: String(cls), id});
                }
                node = node.parentElement;
            }
        }
        candidates.sort((a, b) => {
            const score = (item) => {
                let value = item.depth * 80 + Math.max(0, item.answerCount - selectors.length) * 900;
                if (item.marker) value -= 900;
                if (/formulation|content|que|question/.test(item.className + ' ' + item.id)) value -= 500;
                if (item.nav) value += 5000;
                if (item.text === '此页') value += 5000;
                if (item.text.length < 40) value += 2000;
                return value;
            };
            const aScore = score(a);
            const bScore = score(b);
            return aScore - bScore;
        });
        return candidates[0] || {text: '', assets: statsOf(document.body), depth: 0};
    }
    """
    try:
        context = page.evaluate(js, selectors)
        return {
            "text": clean_text(context.get("text", ""))[:4000],
            "assets": context.get("assets", {}),
        }
    except Exception:
        return {"text": "", "assets": {}}


def _choose_text(qnum: int, context_text: str, body_text: str) -> str:
    context_text = clean_text(context_text)
    body_text = clean_text(body_text)
    weak_body = body_text in {"此页", "This page"} or len(body_text) < 30
    weak_context = context_text in {"此页", "This page"} or len(context_text) < 30

    # The quiz navigation also contains text like "题目 2 此页", which can
    # poison whole-page splitting. The nearest answer container is more
    # reliable whenever it has real question text.
    if not weak_context:
        return context_text[:4000]
    if not weak_body:
        return body_text[:4000]
    return context_text[:4000] if context_text else f"第{qnum}题"


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace(":", "\\:")
