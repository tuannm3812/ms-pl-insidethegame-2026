"""Capture this snapshot's screenshots and checks in Chromium.

Run from this folder: ``python capture.py``. Set CHROMIUM to a Chromium or
headless-shell binary if Playwright's own is not installed. Opens
index.html from disk (seed 27 fixtures, Riverside/home focus) with Google
Fonts blocked, so the system fallback font is used and the capture needs no
network. Records the decision, keyboard and content checks in capture.json.
"""

import asyncio
import json
import os
import pathlib

from playwright.async_api import Browser, Page, async_playwright

HERE = pathlib.Path(__file__).parent
URL = (HERE / "index.html").as_uri()
WIDTHS = (1440, 1024, 900, 861, 768, 390, 375)
PRESS = ".options[data-finding=press] .option"
DECIDE = ".decide[data-finding=press]"


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


async def focused(p: Page) -> str | None:
    """The data-key of the focused control."""
    return await p.evaluate("document.activeElement.dataset.key || null")


async def main() -> None:
    """Save the five agreed views, state checks and an overflow table."""
    notes = {"overflow": {}, "page_errors": [], "state_checks": {}}
    sc = notes["state_checks"]
    exe = os.environ.get("CHROMIUM")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=exe or None)
        p, errors = await open_page(b, 1440, 1000)
        await p.screenshot(path=str(HERE / "1-initial.png"))
        call = p.locator(".change.open").first
        await call.screenshot(path=str(HERE / "2-priority-call.png"))
        sc["adopt_disabled_before_draft"] = await p.is_disabled(
            f"{DECIDE} button[data-act=adopted]"
        )
        sc["best_when"] = await p.locator(
            f"{PRESS} .cost:last-child"
        ).all_inner_texts()
        # Keyboard: Enter drafts, focus stays, Tab moves on to Adopt.
        await p.focus(f"{PRESS}[data-option=a]")
        await p.keyboard.press("Enter")
        sc["focus_after_draft"] = await focused(p)
        await p.keyboard.press("Tab")
        await p.keyboard.press("Tab")
        sc["focus_two_tabs_later"] = await focused(p)
        await p.keyboard.press("Enter")
        sc["focus_after_adopt"] = await focused(p)
        await p.check(f"{DECIDE} input")
        sc["focus_after_in_place"] = await focused(p)
        await call.screenshot(path=str(HERE / "3-selected.png"))
        sc["label_after_adopt"] = await p.inner_text(f"{DECIDE} .state")
        await p.click("#check60")
        await p.wait_for_selector(".checkslot .check")
        await call.screenshot(path=str(HERE / "4-follow-up.png"))
        sc["home_press_badge"] = await p.inner_text(".check b.badge")
        sc["home_press_next"] = await p.inner_text(".check p:nth-of-type(2)")

        # A call that is not adopted is monitoring only.
        await p.click(".change[data-finding=threat] .toggle")
        await p.click("#check60")
        await p.wait_for_selector(
            ".change[data-finding=threat] .checkslot .check"
        )
        sc["threat_not_adopted_next"] = await p.inner_text(
            ".change[data-finding=threat] .check p:nth-of-type(2)"
        )

        # Drafting B clears adoption, implementation and the old check.
        await p.click(f"{PRESS}[data-option=b]")
        sc["after_switch_to_b"] = {
            "label": await p.inner_text(f"{DECIDE} .state"),
            "checks_shown": await p.locator(".checkslot .check").count(),
        }
        # A check still in flight when the draft changes is dropped.
        await p.evaluate("window.OFFLINE_DELAY_MS = 1500")
        await p.click("#check60")
        await p.click(f"{PRESS}[data-option=a]")
        await p.wait_for_timeout(2500)
        sc["stale_check_dropped"] = (
            await p.locator(".checkslot .check").count() == 0
        )
        await p.evaluate("window.OFFLINE_DELAY_MS = 150")

        # Content: one format per metric, fouls apart, role-led insight.
        sc["bars"] = await p.locator("#bars .row").all_inner_texts()
        await p.click("#squad button:has-text('Brennan')")
        sc["brennan_insight"] = await p.inner_text("#pcard .insight")
        sc["brennan_chips"] = await p.locator(
            "#pcard .chips .chip"
        ).all_inner_texts()
        await p.click("#squad button:has-text('Navarro')")
        sc["navarro_chips"] = await p.locator(
            "#pcard .chips .chip"
        ).all_inner_texts()

        # Another focus team starts clean, then checks its own targets.
        await p.click("#check60")
        await p.wait_for_selector(".checkslot .check")
        await p.select_option("#focus", "away")
        await p.wait_for_timeout(1500)
        await p.wait_for_selector("#check60")
        sc["away_checks_after_switch"] = await p.locator(
            ".checkslot .check"
        ).count()
        await p.click("#check60")
        await p.wait_for_selector(".checkslot .check")
        sc["away_press_badge"] = await p.inner_text(".check b.badge")
        notes["page_errors"] += errors
        await p.close()

        p, errors = await open_page(b, 390, 844)
        await p.screenshot(path=str(HERE / "5-mobile.png"))
        notes["page_errors"] += errors
        await p.close()

        for w in WIDTHS:
            p, errors = await open_page(b, w, 1000)
            await p.click(f"{PRESS}[data-option=a]")
            await p.click("#check60")
            await p.wait_for_selector(".checkslot .check")
            sw = await p.evaluate("document.documentElement.scrollWidth")
            notes["overflow"][w] = sw
            notes["page_errors"] += errors
            await p.close()
        await b.close()
    (HERE / "capture.json").write_text(json.dumps(notes, indent=2) + "\n")
    print(json.dumps(notes, indent=1))


asyncio.run(main())
