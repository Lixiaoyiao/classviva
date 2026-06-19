#!/usr/bin/env python3
"""本地网页控制台入口。

运行 `python app.py` 后，在浏览器打开 http://127.0.0.1:8765。
"""

from __future__ import annotations

import json
import mimetypes
import importlib
import importlib.util
import pprint
import shutil
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"


def ensure_config() -> None:
    config_path = ROOT / "config.py"
    example_path = ROOT / "config.example.py"
    if not config_path.exists() and example_path.exists():
        shutil.copy(example_path, config_path)
        print("[配置] 已创建 config.py，请填写 API Key 后继续使用 AI 功能。")


ensure_config()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(ROOT))

import config  # noqa: E402


class State:
    browser: object | None = None
    groups: list[dict] = []
    results: list[dict] = []


state = State()


class Handler(BaseHTTPRequestHandler):
    server_version = "ClassvivaLocal/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._send_json(status_payload())
            return
        if parsed.path == "/api/config":
            self._send_json(config_payload())
            return

        rel = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
        path = (WEB_DIR / rel).resolve()
        if WEB_DIR not in path.parents and path != WEB_DIR:
            self._send_error(403, "Forbidden")
            return
        if not path.exists() or not path.is_file():
            self._send_error(404, "Not found")
            return

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            parsed = urlparse(self.path)
            routes = {
                "/api/start": api_start,
                "/api/extract": api_extract,
                "/api/solve": api_solve,
                "/api/vision-solve": api_vision_solve,
                "/api/fill": api_fill,
                "/api/close": api_close,
                "/api/config": api_save_config,
                "/api/debug-controls": api_debug_controls,
                "/api/debug-ancestors": api_debug_ancestors,
            }
            if parsed.path not in routes:
                self._send_error(404, "Unknown API")
                return
            self._send_json(routes[parsed.path](payload))
        except Exception as exc:
            traceback.print_exc()
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args) -> None:
        print("[Web]", fmt % args)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)


def api_start(payload: dict) -> dict:
    ClassvivaBrowser = _runtime("browser").ClassvivaBrowser
    url = (payload.get("url") or getattr(config, "CLASSVIVA_URL", "") or "").strip()
    headless = bool(payload.get("headless", False))

    if state.browser:
        state.browser.close()

    state.browser = ClassvivaBrowser(headless=headless)
    state.browser.start(url=url or None)
    state.groups = []
    state.results = []
    return {"ok": True, "page": state.browser.page_info(), "message": "浏览器已启动"}


def api_extract(payload: dict) -> dict:
    browser = require_browser()
    groups, warnings = _extract_current_groups(browser, bool(payload.get("visionFallback")))
    state.groups = groups
    state.results = []
    return {"ok": True, "groups": groups, "page": browser.page_info(), "warnings": warnings}


def _extract_current_groups(browser, vision_fallback: bool = False) -> tuple[list[dict], list[str]]:
    groups = browser.extract_question_groups()
    warnings = []

    if vision_fallback and groups and _has_weak_text(groups):
        try:
            read_questions_from_image = _runtime("vision").read_questions_from_image
            visual = read_questions_from_image(browser.screenshot_bytes(), groups)
            if visual.get("success"):
                for group in groups:
                    text = visual["questions"].get(group["qnum"])
                    if text:
                        group["text"] = text
            else:
                warnings.append(visual.get("error", "视觉兜底未返回可用题面"))
        except Exception as exc:
            warnings.append(f"视觉兜底失败，已保留 DOM 提取结果：{exc}")

    return groups, warnings


def api_solve(payload: dict) -> dict:
    solve_all = _runtime("solver").solve_all
    groups = payload.get("groups") or state.groups
    if not groups:
        return {"ok": False, "error": "还没有提取到题目"}
    results = solve_all(groups)
    state.results = results
    return {"ok": True, "results": results}


def api_vision_solve(payload: dict) -> dict:
    solve_page_from_image = _runtime("vision").solve_page_from_image
    browser = require_browser()
    groups, warnings = _extract_current_groups(browser, bool(payload.get("visionFallback")))
    if not groups:
        groups = payload.get("groups") or state.groups
    state.groups = groups
    state.results = []
    visual = solve_page_from_image(browser.screenshot_bytes(), groups)
    if not visual.get("success"):
        return {"ok": False, "groups": groups, "warnings": warnings, **visual}

    results = []
    for item in visual["items"]:
        group = _find_group(groups, item.get("qnum"))
        answers = item.get("answers", [])
        success = _has_real_answers(answers)
        result = {
            "success": success,
            "answers": answers if success else [],
            "raw": visual.get("raw", ""),
            "vision": True,
            "confidence": item.get("confidence", "unknown"),
            "note": item.get("note", ""),
            "error": "" if success else "视觉模型未生成有效答案",
        }
        if group:
            result["group"] = group
        else:
            result["group"] = {
                "qnum": item.get("qnum"),
                "text": "视觉识别结果，未匹配到网页输入框",
                "slots": [],
            }
        results.append(result)

    state.results = results
    return {"ok": True, "groups": groups, "results": results, "visual": visual, "warnings": warnings}


def api_fill(payload: dict) -> dict:
    browser = require_browser()
    results = payload.get("results") or state.results
    if not results:
        return {"ok": False, "error": "还没有可填写的答案"}

    results = browser.rebind_results_to_current_page(results)
    fillable = [r for r in results if r.get("group", {}).get("slots")]
    count = browser.fill_all(fillable)
    state.results = results
    return {"ok": True, "filled": count}


def _has_real_answers(answers: list) -> bool:
    for answer in answers or []:
        text = str(answer).strip()
        if text and text not in {"?", "No_answer"}:
            return True
    return False


def api_debug_controls(_: dict) -> dict:
    browser = require_browser()
    page = browser.page
    if not page:
        return {"ok": False, "error": "浏览器页面不可用"}
    controls = page.evaluate(
        """() => Array.from(document.querySelectorAll('input, textarea, select, button, [role], [contenteditable="true"]')).map((el, index) => {
            const rect = el.getBoundingClientRect();
            const tag = el.tagName.toLowerCase();
            const type = el.getAttribute('type') || '';
            const id = el.id || '';
            const name = el.getAttribute('name') || '';
            const sensitive = ['password', 'hidden'].includes(type.toLowerCase())
                || /token|password|passwd|pwd|secret|key/i.test(id + ' ' + name);
            const answerLike = /answer|AnSwEr/i.test(id + ' ' + name) || tag === 'select' || ['radio', 'checkbox'].includes(type.toLowerCase());
            return {
                index,
                tag,
                type,
                id,
                name,
                value: sensitive ? '[redacted]' : (answerLike ? (el.getAttribute('value') || el.value || '') : ''),
                role: el.getAttribute('role') || '',
                text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                visible: rect.width > 0 && rect.height > 0,
                options: tag === 'select'
                    ? Array.from(el.options || []).map(o => ({value: o.value || '', text: (o.textContent || '').trim()}))
                    : []
            };
        })"""
    )
    return {"ok": True, "controls": controls}


def api_debug_ancestors(payload: dict) -> dict:
    browser = require_browser()
    page = browser.page
    selector = payload.get("selector") or ""
    if not page:
        return {"ok": False, "error": "浏览器页面不可用"}
    if not selector:
        return {"ok": False, "error": "缺少 selector"}
    ancestors = page.evaluate(
        """(selector) => {
            const el = document.querySelector(selector);
            if (!el) return [];
            const rows = [];
            let node = el;
            for (let depth = 0; node && depth < 14; depth += 1) {
                const rect = node.getBoundingClientRect();
                rows.push({
                    depth,
                    tag: node.tagName.toLowerCase(),
                    id: node.id || '',
                    className: String(node.className || ''),
                    name: node.getAttribute('name') || '',
                    text: (node.innerText || node.textContent || '').trim().slice(0, 600),
                    visible: rect.width > 0 && rect.height > 0,
                    answerCount: node.querySelectorAll ? node.querySelectorAll('[id*="AnSwEr"], [name*="AnSwEr"]').length : 0
                });
                node = node.parentElement;
            }
            return rows;
        }""",
        selector,
    )
    return {"ok": True, "ancestors": ancestors}


def api_close(_: dict) -> dict:
    if state.browser:
        state.browser.close()
    state.browser = None
    state.groups = []
    state.results = []
    return {"ok": True, "message": "浏览器已关闭"}


def status_payload() -> dict:
    page = state.browser.page_info() if state.browser else {"started": False, "url": "", "title": ""}
    deps = dependency_payload()
    return {
        "ok": True,
        "page": page,
        "groupCount": len(state.groups),
        "resultCount": len(state.results),
        "visionConfigured": _has_real_key(getattr(config, "VISION_API_KEY", "")),
        "textModel": getattr(config, "DEEPSEEK_MODEL", ""),
        "visionModel": getattr(config, "VISION_MODEL", ""),
        "dependencies": deps,
    }


def config_payload() -> dict:
    return {
        "ok": True,
        "textKeySet": _has_real_key(getattr(config, "DEEPSEEK_API_KEY", "")),
        "textBaseUrl": getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "textModel": getattr(config, "DEEPSEEK_MODEL", "deepseek-chat"),
        "visionKeySet": _has_real_key(getattr(config, "VISION_API_KEY", "")),
        "visionBaseUrl": getattr(config, "VISION_BASE_URL", "https://api.openai.com/v1"),
        "visionModel": getattr(config, "VISION_MODEL", "gpt-4o-mini"),
        "classvivaUrl": getattr(config, "CLASSVIVA_URL", ""),
        "webHost": getattr(config, "WEB_HOST", "127.0.0.1"),
        "webPort": int(getattr(config, "WEB_PORT", 8765)),
    }


def dependency_payload() -> dict:
    playwright_installed = importlib.util.find_spec("playwright") is not None
    openai_installed = importlib.util.find_spec("openai") is not None
    return {
        "playwright": playwright_installed,
        "openai": openai_installed,
        "ready": playwright_installed and openai_installed,
    }


def api_save_config(payload: dict) -> dict:
    global config
    current = config_payload()
    text_key = str(payload.get("textApiKey") or "").strip()
    vision_key = str(payload.get("visionApiKey") or "").strip()

    values = {
        "DEEPSEEK_API_KEY": text_key if text_key else getattr(config, "DEEPSEEK_API_KEY", ""),
        "DEEPSEEK_BASE_URL": str(payload.get("textBaseUrl") or current["textBaseUrl"]).strip(),
        "DEEPSEEK_MODEL": str(payload.get("textModel") or current["textModel"]).strip(),
        "VISION_API_KEY": vision_key if vision_key else getattr(config, "VISION_API_KEY", ""),
        "VISION_BASE_URL": str(payload.get("visionBaseUrl") or current["visionBaseUrl"]).strip(),
        "VISION_MODEL": str(payload.get("visionModel") or current["visionModel"]).strip(),
        "CLASSVIVA_URL": str(payload.get("classvivaUrl") or "").strip(),
        "WEB_HOST": str(payload.get("webHost") or current["webHost"]).strip(),
        "WEB_PORT": int(payload.get("webPort") or current["webPort"]),
        "SELECTORS": getattr(config, "SELECTORS", {}),
        "TIMEOUT": int(getattr(config, "TIMEOUT", 30000)),
        "EXTRACT_WAIT": int(getattr(config, "EXTRACT_WAIT", 5000)),
        "WAIT_BETWEEN": float(getattr(config, "WAIT_BETWEEN", 1.5)),
    }
    _write_config(values)
    importlib.invalidate_caches()
    config = importlib.reload(config)
    return {"ok": True, "config": config_payload(), "message": "配置已保存到 config.py"}


def require_browser() -> object:
    if not state.browser:
        raise RuntimeError("浏览器还没有启动")
    return state.browser


def _has_weak_text(groups: list[dict]) -> bool:
    for group in groups:
        text = str(group.get("text") or "").strip()
        quality = group.get("quality") or {}
        if quality.get("needs_vision"):
            return True
        if len(text) < 25 or text == f"第{group.get('qnum')}题":
            return True
    return False


def _find_group(groups: list[dict], qnum: int | None) -> dict | None:
    for group in groups:
        if group.get("qnum") == qnum:
            return group
    return None


def _runtime(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            raise RuntimeError("Playwright 未安装。请先运行：pip install -r requirements.txt，然后运行：playwright install chromium") from exc
        if exc.name == "openai":
            raise RuntimeError("OpenAI SDK 未安装。请先运行：pip install -r requirements.txt") from exc
        raise


def _has_real_key(value: str) -> bool:
    text = str(value or "").strip()
    return bool(text and "在此填入" not in text and "你的" not in text)


def _write_config(values: dict) -> None:
    lines = [
        '"""本机配置文件，由前端设置页面生成。不要提交到公开仓库。"""',
        "",
        "# 文本解题模型",
        f"DEEPSEEK_API_KEY = {values['DEEPSEEK_API_KEY']!r}",
        f"DEEPSEEK_BASE_URL = {values['DEEPSEEK_BASE_URL']!r}",
        f"DEEPSEEK_MODEL = {values['DEEPSEEK_MODEL']!r}",
        "",
        "# 多模态视觉模型",
        f"VISION_API_KEY = {values['VISION_API_KEY']!r}",
        f"VISION_BASE_URL = {values['VISION_BASE_URL']!r}",
        f"VISION_MODEL = {values['VISION_MODEL']!r}",
        "",
        "# classviva 作业页面",
        f"CLASSVIVA_URL = {values['CLASSVIVA_URL']!r}",
        "",
        "# 本地前端控制台",
        f"WEB_HOST = {values['WEB_HOST']!r}",
        f"WEB_PORT = {values['WEB_PORT']!r}",
        "",
        "# classviva 网页选择器",
        "SELECTORS = " + pprint.pformat(values["SELECTORS"], width=100, sort_dicts=False),
        "",
        f"TIMEOUT = {values['TIMEOUT']!r}",
        f"EXTRACT_WAIT = {values['EXTRACT_WAIT']!r}",
        f"WAIT_BETWEEN = {values['WAIT_BETWEEN']!r}",
        "",
    ]
    (ROOT / "config.py").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    host = getattr(config, "WEB_HOST", "127.0.0.1")
    port = int(getattr(config, "WEB_PORT", 8765))
    # Playwright sync API is thread-affine. Keep all browser operations on the
    # same server thread instead of using ThreadingHTTPServer.
    server = HTTPServer((host, port), Handler)
    print(f"[Web] 本地控制台已启动: http://{host}:{port}")
    print("[Web] 按 Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Web] 正在退出...")
    finally:
        if state.browser:
            state.browser.close()
        server.server_close()


if __name__ == "__main__":
    main()
