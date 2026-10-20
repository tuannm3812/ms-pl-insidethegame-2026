"""Capture this snapshot's screenshots and overflow checks in Chromium.

Run from this folder: ``python capture.py``. Opens index.html from disk
(seed 27 fixtures, Riverside/home focus) with Google Fonts blocked, so the
system fallback font is used and the capture needs no network.
"""

import asyncio
import json
import pathlib

from playwright.async_api import Browser, Page, async_playwright

HERE = pathlib.Path(__file__).parent
URL = (HERE / "index.html").as_uri()
WIDTHS = (1440, 1024, 900, 861, 768, 390, 375)


async def open_page(
    browser: Browser, width: int, height: int
) -> tuple[Page, list[str]]:
    """Open the snapshot at a viewport and wait for the analyst calls."""
    page = await browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    await page.route("**/fonts.gstatic.com/**", lambda r: r.abort())
    await page.goto(URL)
    await page.wait_for_selector("#check60", timeout=30000)
    await page.wait_for_timeout(1500)
    return page, errors


async def main() -> None:
    """Save the five agreed views plus an overflow table."""
    notes = {"overflow": {}, "page_errors": []}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium"
        )
        p, errors = await open_page(b, 1440, 1000)
        await p.screenshot(path=str(HERE / "1-initial.png"))
        first = p.locator(".change").first
        await first.scroll_into_view_if_needed()
        await first.screenshot(path=str(HERE / "2-priority-call.png"))
        await p.click(".options[data-finding=press] .option[data-option=a]")
        await first.screenshot(path=str(HERE / "3-selected.png"))
        await p.click("#check60")
        await p.wait_for_selector(".checkslot .check")
        await first.screenshot(path=str(HERE / "4-follow-up.png"))
        notes["page_errors"] += errors
        await p.close()

        p, errors = await open_page(b, 390, 844)
        await p.screenshot(path=str(HERE / "5-mobile.png"))
        notes["page_errors"] += errors
        await p.close()

        for w in WIDTHS:
            p, errors = await open_page(b, w, 1000)
            sw = await p.evaluate("document.documentElement.scrollWidth")
            notes["overflow"][w] = sw
            notes["page_errors"] += errors
            await p.close()
        await b.close()
    (HERE / "capture.json").write_text(json.dumps(notes, indent=2) + "\n")
    print(json.dumps(notes))


asyncio.run(main())
