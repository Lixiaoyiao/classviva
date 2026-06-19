#!/usr/bin/env python3
"""
classviva 数学题自动求解器
============================
流程：浏览器打开网页 → 按大题分组提取题目 → AI整题求解 → 格式化 → 自动填写

用法：
    python main.py                          # 交互模式
    python main.py --url <classviva_url>    # 直接指定URL
    python main.py --demo                   # 演示模式
    python main.py --selectors              # CSS选择器分析
"""

import sys
import os
import shutil
import argparse
import json
from datetime import datetime

# 首次使用：自动从模板创建 config.py
_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
_example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.example.py")
if not os.path.exists(_config) and os.path.exists(_example):
    shutil.copy(_example, _config)
    print("已创建 config.py，请打开填入你的 API Key 和作业链接后重新运行。")
    sys.exit(0)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from browser import ClassvivaBrowser
from solver import solve_all
from vision import solve_groups_with_vision, vision_configured
from config import CLASSVIVA_URL


def interactive_mode(url: str = None, headless: bool = False, force_vision: bool = False, auto_vision: bool = True):
    """交互模式：可连续做多节作业，不关浏览器"""
    url = url or CLASSVIVA_URL
    if not url:
        url = input("作业链接: ").strip()
        if not url:
            print("需要链接才能启动。")
            return

    browser = ClassvivaBrowser(headless=headless)

    print("\n" + "=" * 55)
    print("  classviva 数学题自动求解器 v3")
    print("=" * 55)

    try:
        browser.start(url=url)
        print("页面加载中...")
        browser.page.wait_for_timeout(3000)
        browser.wait_for_user("确认页面是作业页面后按 Enter...")

        round_num = 0
        while True:
            round_num += 1

            # 1. 提取
            print(f"\n[1/4] 提取题目...")
            groups = browser.extract_question_groups()
            if not groups:
                print("[!] 未提取到题目，检查页面。")
                continue

            weak_groups = []
            for g in groups:
                quality = g.get("quality", {})
                reasons = "、".join(quality.get("reasons", []))
                suffix = f"｜建议视觉: {reasons}" if quality.get("needs_vision") else ""
                print(f"  第{g['qnum']}题: {len(g['slots'])}空｜质量 {quality.get('score', 'n/a')}{suffix}")
                if quality.get("needs_vision"):
                    weak_groups.append(g)

            # 2. 求解
            use_vision = force_vision
            if auto_vision and weak_groups and vision_configured() and not force_vision:
                choice = input(f"\n检测到 {len(weak_groups)} 道题可能含图片或提取不完整，使用视觉兜底? (Enter=是, n=否): ").strip().lower()
                use_vision = choice != "n"

            if use_vision:
                print(f"\n[2/4] 多模态视觉求解...")
                results = solve_groups_with_vision(browser.screenshot_bytes(), groups)
            else:
                print(f"\n[2/4] AI 求解（文本模型）...")
                results = solve_all(groups)

            # 3. 审核
            print(f"\n[3/4] 审核 —— Enter确认, x修改, q跳过")
            print("-" * 55)
            for r in results:
                g = r["group"]
                answers = r.get("answers", [])
                status = "OK" if r["success"] else "FAIL"

                vision_note = "｜视觉" if r.get("vision") else ""
                confidence = f"｜置信 {r.get('confidence')}" if r.get("confidence") else ""
                print(f"\n第{g['qnum']}题 [{status}{vision_note}{confidence}]: {answers}")
                print(f"  摘要: {g['text'][:150]}")

                if r["success"]:
                    choice = input("  > ").strip().lower()
                    if choice == "q":
                        break
                    elif choice == "x":
                        new = input(f"  正确({len(answers)}个,逗号分隔): ").strip()
                        if new:
                            parts = [a.strip() for a in new.split(",")]
                            if len(parts) == len(answers):
                                r["answers"] = parts
                                print(f"  -> {parts}")
                else:
                    manual = input(f"  手动输入({g['slots']}个,逗号分隔): ").strip()
                    if manual:
                        r["answers"] = [a.strip() for a in manual.split(",")]
                        r["success"] = True

            # 4. 填写
            ok_count = sum(1 for r in results if r["success"])
            if ok_count > 0:
                print(f"\n[4/4] 填入网页 ({ok_count}/{len(results)}题)...")
                go = input("确认填写? (Enter=OK, n=跳过): ").strip().lower()
                if go != "n":
                    browser.fill_all(results)
                    browser.screenshot(f"classviva_r{round_num}.png")

            save_results(results)

            browser.wait_for_user("请在浏览器中提交，然后打开下一节作业，完成后按 Enter...")
            nxt = input("继续下一节? (Enter=继续, q=退出): ").strip().lower()
            if nxt == "q":
                break

        print("\n全部完成。")
        browser.wait_for_user("按 Enter 关闭浏览器...")

    finally:
        browser.close()


def save_results(results: list[dict]):
    """保存结果到 JSON 文件"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"classviva_results_{timestamp}.json"
    clean = []
    for r in results:
        g = r.get("group", {})
        clean.append({
            "qnum": g.get("qnum"),
            "text": g.get("text", "")[:500],
            "answers": r.get("answers", []),
            "success": r.get("success", False),
            "raw": r.get("raw", "")[:500],
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"[保存] {path}")


def demo_mode():
    """演示模式：测试解题功能"""
    print("\n" + "=" * 50)
    print("  演示模式 - 多空题求解测试")
    print("=" * 50 + "\n")

    test_groups = [
        {
            "qnum": 1,
            "text": (
                "如果极限存在, 请求出极限. 如果极限不存在, 请输入 'DNE'.\n"
                "lim (x,y)->(2,1) (7x^4*y - 2x^2 + y^2)\n"
                "极限:"
            ),
            "slots": [{"subnum": 1}],
        },
        {
            "qnum": 2,
            "text": (
                "求极限 (如果极限不存在, 请输入 DNE).\n"
                "lim (x,y)->(0,0) (-5x+y)^2/(25x^2+y^2)\n"
                "1) 沿X轴:\n"
                "2) 沿Y轴:\n"
                "3) 沿直线 y=x:\n"
                "4) 极限:"
            ),
            "slots": [{"subnum": 1}, {"subnum": 2}, {"subnum": 3}, {"subnum": 4}],
        },
    ]

    results = solve_all(test_groups)

    print("\n结果:")
    for r in results:
        g = r["group"]
        print(f"  第{g['qnum']}题: {r.get('answers', r.get('error'))}")


def selector_helper():
    """CSS 选择器分析工具"""
    browser = ClassvivaBrowser(headless=False)
    try:
        browser.start()
        page = browser.page
        print("\n浏览器已打开。手动登录 classviva 并打开题目页面。")
        browser.wait_for_user("准备好后按 Enter 分析页面...")

        print(f"\n当前 URL: {page.url}")
        print(f"页面标题: {page.title()}")
        print()

        # 打印输入框
        inputs = page.query_selector_all("input[id*='AnSwEr'], input[type='text']")
        print(f"=== 输入框 ({len(inputs)} 个) ===")
        for inp in inputs[:20]:
            print(f"  id={inp.get_attribute('id')}  name={inp.get_attribute('name')}  type={inp.get_attribute('type')}")

        # 打印是否有 MathJax script 标签
        tex_count = page.evaluate("() => document.querySelectorAll('script[type*=\"math\"]').length")
        print(f"\nMathJax LaTeX script 标签数: {tex_count}")

        # 打印 div.formulation 数量
        form_count = page.evaluate("() => document.querySelectorAll('div.formulation').length")
        print(f"div.formulation 数量: {form_count}")
        media_count = page.evaluate("() => document.querySelectorAll('img, canvas, svg').length")
        print(f"img/canvas/svg 数量: {media_count}")

        # 打印页面前1000字
        body = page.inner_text("body")
        print(f"\n=== 页面正文 (前1000字) ===")
        print(body[:1000])

        browser.wait_for_user("\n按 Enter 关闭...")
    finally:
        browser.close()


def main():
    parser = argparse.ArgumentParser(description="classviva 数学题自动求解器")
    parser.add_argument("--url", help="classviva 作业页面 URL")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--demo", action="store_true", help="演示模式")
    parser.add_argument("--selectors", action="store_true", help="页面结构分析")
    parser.add_argument("--vision", action="store_true", help="强制使用多模态截图求解")
    parser.add_argument("--no-auto-vision", action="store_true", help="提取质量低时也不提示视觉兜底")
    args = parser.parse_args()

    if args.demo:
        demo_mode()
    elif args.selectors:
        selector_helper()
    else:
        interactive_mode(
            url=args.url,
            headless=args.headless,
            force_vision=args.vision,
            auto_vision=not args.no_auto_vision,
        )


if __name__ == "__main__":
    main()
