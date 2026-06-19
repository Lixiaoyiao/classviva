"""浏览器自动化 - 使用 Playwright 操作 classviva 网页"""

import time
import os
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from config import SELECTORS, TIMEOUT, WAIT_BETWEEN
try:
    from config import EXTRACT_WAIT
except ImportError:
    EXTRACT_WAIT = 5000
from extractor import extract_question_groups

USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser_profile")


class ClassvivaBrowser:
    """classviva 网页自动化操作"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self, url: str = None):
        """启动浏览器并直接导航到指定 URL"""
        self.playwright = sync_playwright().start()
        os.makedirs(USER_DATA_DIR, exist_ok=True)

        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                channel="msedge",
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                ignore_default_args=["--no-sandbox"],
            )
            print("[浏览器] 已启动 Edge")
        except Exception:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=USER_DATA_DIR,
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
            )
            print("[浏览器] 已启动 Chromium")

        self.browser = self.context.browser
        pages = self.context.pages

        # 关掉多余标签页，只留一个
        for p in pages[1:]:
            p.close()
        self.page = pages[0] if pages else self.context.new_page()

        if url:
            self.goto(url)

    def goto(self, url: str):
        """导航到指定 URL（容忍重定向）"""
        if not self.page:
            raise RuntimeError("浏览器未启动")
        print(f"[导航] {url}")
        try:
            self.page.goto(url, timeout=TIMEOUT, wait_until="domcontentloaded")
        except Exception as e:
            # 页面可能重定向了，不崩溃
            print(f"  [提示] 页面跳转: {str(e)[:80]}")
        self.page.wait_for_timeout(2000)

    def extract_question_groups(self) -> list[dict]:
        """自适应提取题目、空位和质量信息。"""
        if not self.page:
            raise RuntimeError("浏览器未启动")
        return extract_question_groups(self.page, SELECTORS, EXTRACT_WAIT)

    def fill_slot(self, slot: dict, answer: str) -> bool:
        """填写单个答案槽（自动判断 text 还是 radio）"""
        if not self.page:
            return False
        input_id = slot["input_id"]

        selector = slot.get("selector") or (f"input[id='{input_id}']" if input_id else "")
        inp = self.page.query_selector(selector)
        if not inp:
            return False
        actual_type = (inp.get_attribute("type") or "text").lower()
        tag_name = inp.evaluate("el => el.tagName.toLowerCase()")

        if tag_name == "select":
            return self._fill_select(inp, slot, answer)

        if actual_type in ("radio", "checkbox"):
            return self._fill_choice(slot, answer)
        else:
            inp.click()
            inp.fill("")
            inp.type(answer, delay=30)
            return True

    def _fill_select(self, inp, slot: dict, answer: str) -> bool:
        answer = str(answer).strip()
        options = slot.get("options") or []
        candidates = _answer_candidates(answer)
        for option in options:
            value = str(option.get("value", "")).strip()
            text = str(option.get("text", "")).strip()
            if value in candidates or text in candidates:
                inp.select_option(value=value)
                return True
        try:
            inp.select_option(label=answer)
            return True
        except Exception:
            return False

    def _fill_choice(self, slot: dict, answer: str) -> bool:
        if not self.page:
            return False
        candidates = _answer_candidates(answer)
        input_id = slot.get("input_id", "")
        input_name = slot.get("input_name", "")
        selector_parts = []
        for value in candidates:
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            if input_id:
                selector_parts.append(f"input[id='{input_id}'][value='{escaped}']")
            if input_name:
                selector_parts.append(f"input[name='{input_name}'][value='{escaped}']")
        if selector_parts:
            option = self.page.query_selector(", ".join(selector_parts))
            if option:
                option.click()
                return True
        return False

    def fill_group(self, group: dict, answers: list[str]) -> int:
        """填写一道大题的所有空，返回成功数量"""
        slots = group["slots"]
        ok = 0
        for i, raw_answer in enumerate(answers):
            if i >= len(slots):
                break
            ans = str(raw_answer).strip()
            if not ans or ans in {"?", "No_answer"}:
                continue
            if self.fill_slot(slots[i], ans):
                print(f"  [OK] 第{group['qnum']}题-空{i+1}: {ans}")
                ok += 1
            time.sleep(WAIT_BETWEEN)
        return ok

    def rebind_results_to_current_page(self, results: list[dict]) -> list[dict]:
        """如果结果还绑着旧页面输入框，按当前页的题号重新绑定。"""
        if not self.page:
            return results

        stale_results = []
        for result in results:
            group = result.get("group") or {}
            qnum = group.get("qnum")
            if qnum is None:
                continue
            if not group.get("slots") or not self._group_slots_exist(group):
                stale_results.append(result)

        if not stale_results:
            return results

        current_groups = self.extract_question_groups()
        current_by_qnum = {group.get("qnum"): group for group in current_groups}
        for result in stale_results:
            qnum = (result.get("group") or {}).get("qnum")
            current = current_by_qnum.get(qnum)
            if current:
                result["group"] = current

        return results

    def _group_slots_exist(self, group: dict) -> bool:
        slots = group.get("slots") or []
        if not slots:
            return False
        return all(self._slot_exists(slot) for slot in slots)

    def _slot_exists(self, slot: dict) -> bool:
        if not self.page:
            return False
        selector = slot.get("selector")
        if selector:
            try:
                if self.page.query_selector(selector):
                    return True
            except Exception:
                pass
        return bool(self.page.evaluate(
            """slot => {
                const id = slot.input_id || '';
                const name = slot.input_name || '';
                if (id && document.getElementById(id)) return true;
                if (!name) return false;
                return Array.from(document.querySelectorAll('[name]')).some(el => el.getAttribute('name') === name);
            }""",
            slot,
        ))

    def fill_all(self, results: list[dict]) -> int:
        """填写所有题目"""
        total = 0
        for r in results:
            answers = [str(answer).strip() for answer in r.get("answers", [])]
            if any(answer and answer not in {"?", "No_answer"} for answer in answers):
                total += self.fill_group(r["group"], answers)
        print(f"[填写] 共填入 {total} 个答案")
        return total

    def wait_for_user(self, msg: str = "请在浏览器中完成操作后按 Enter 继续..."):
        input(f"\n{msg}")

    def screenshot(self, path: str = "page.png"):
        if self.page:
            self.page.screenshot(path=path, full_page=True)
            print(f"[截图] 已保存至 {path}")

    def screenshot_bytes(self) -> bytes:
        if not self.page:
            raise RuntimeError("浏览器未启动")
        return self.page.screenshot(full_page=True, type="png")

    def page_info(self) -> dict:
        if not self.page:
            return {"started": False, "url": "", "title": ""}
        return {"started": True, "url": self.page.url, "title": self.page.title()}

    def close(self):
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()
        print("[浏览器] 已关闭")


def _answer_candidates(answer: str) -> set[str]:
    text = str(answer).strip()
    lower = text.lower()
    mapping = {
        "是": {"是", "yes", "y", "true", "1", "A", "a"},
        "否": {"否", "no", "n", "false", "0", "B", "b"},
        "yes": {"是", "yes", "y", "true", "1", "A", "a"},
        "no": {"否", "no", "n", "false", "0", "B", "b"},
        "true": {"是", "yes", "y", "true", "1", "A", "a"},
        "false": {"否", "no", "n", "false", "0", "B", "b"},
    }
    candidates = {text, lower, text.upper()}
    candidates.update(mapping.get(text, set()))
    candidates.update(mapping.get(lower, set()))
    return candidates
