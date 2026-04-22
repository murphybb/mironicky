from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the browser regression for PDF import to argument graph workbench."
    )
    parser.add_argument(
        "--frontend-url",
        default="http://127.0.0.1:4174",
        help="Frontend server URL. The script adds workspace_id and page query params.",
    )
    parser.add_argument(
        "--workspace-id",
        default=f"ws-e2e-argument-{int(time.time())}",
        help="Workspace id used by this regression run.",
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Absolute or relative path to a real PDF to upload.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=300000,
        help="Maximum wait for PDF extraction and graph materialization.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window for visual inspection.",
    )
    return parser.parse_args()


def _require_pdf(path: str) -> Path:
    pdf_path = Path(path).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise SystemExit(f"Expected a .pdf file, got: {pdf_path}")
    return pdf_path


def _import_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Python Playwright is not installed. Install it with: "
            "python -m pip install playwright && python -m playwright install chromium"
        ) from exc
    return sync_playwright, expect, PlaywrightTimeoutError


def _overlaps(left: dict[str, float], right: dict[str, float]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


def main() -> int:
    args = _parse_args()
    pdf_path = _require_pdf(args.pdf)
    sync_playwright, expect, PlaywrightTimeoutError = _import_playwright()

    base_url = args.frontend_url.rstrip("/")
    import_url = f"{base_url}/?workspace_id={args.workspace_id}&page=import"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        try:
            page.goto(import_url, wait_until="domcontentloaded", timeout=30000)
            expect(page.locator(".upload-zone")).to_contain_text("点击上传文献")

            page.locator('input[type="file"]').set_input_files(str(pdf_path))
            expect(page.locator("#cand-count")).to_be_visible(timeout=args.timeout_ms)
            page.locator('.cand-card[id^="cc-"]').first.wait_for(
                state="visible", timeout=args.timeout_ms
            )

            page.get_by_role("button", name="全部确认").click()
            expect(page.get_by_role("dialog")).to_contain_text("确认全部入库")
            page.get_by_role("button", name="确认入库").click()

            page.wait_for_url("**page=workbench**", timeout=args.timeout_ms)
            first_node = page.locator(".graph-node").first
            first_node.wait_for(state="visible", timeout=args.timeout_ms)
            node_count = page.locator(".graph-node").count()
            if node_count < 1:
                raise AssertionError("No graph nodes were rendered after candidate confirmation.")
            node_boxes = [
                (index, page.locator(".graph-node").nth(index).bounding_box())
                for index in range(node_count)
            ]
            visible_boxes = [(index, box) for index, box in node_boxes if box is not None]
            for left_index, left_box in visible_boxes:
                for right_index, right_box in visible_boxes:
                    if right_index <= left_index:
                        continue
                    if _overlaps(left_box, right_box):
                        raise AssertionError(
                            f"Graph nodes overlap after auto layout: {left_index} and {right_index}"
                        )

            first_node.click(force=True)
            expect(page.locator(".wb-inspector")).to_contain_text("图谱洞察", timeout=30000)
            expect(page.locator(".insight-card")).to_have_count(4, timeout=30000)
            if page.locator(".graph-node.sel").count() < 1:
                raise AssertionError("Selected graph node did not receive the selected highlight.")
            if page.locator(".graph-node.related").count() < 1:
                raise AssertionError("Connected graph nodes did not receive related highlights.")
            if page.locator(".edge-path.edge-active").count() < 1:
                raise AssertionError("Connected graph edges did not receive active highlights.")

            zoom_before = page.locator(".zoom-hud").inner_text(timeout=10000)
            page.locator(".canvas-area").hover()
            page.mouse.wheel(0, -600)
            page.wait_for_timeout(300)
            zoom_after = page.locator(".zoom-hud").inner_text(timeout=10000)
            if zoom_before == zoom_after:
                raise AssertionError("Zoom HUD did not change after mouse wheel.")

            box = first_node.bounding_box()
            if box is None:
                raise AssertionError("Cannot locate first graph node for drag test.")
            page.mouse.move(box["x"] + 20, box["y"] + 20)
            page.mouse.down()
            page.mouse.move(box["x"] + 120, box["y"] + 90, steps=8)
            page.mouse.up()

            print(
                "workbench argument graph regression passed: "
                f"workspace_id={args.workspace_id}, nodes={node_count}"
            )
            return 0
        except PlaywrightTimeoutError as exc:
            print(f"Playwright timed out: {exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
