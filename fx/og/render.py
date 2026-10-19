"""Render og.html to site/assets/og.png (1200x630). Needs: pip install playwright.

Set CHROMIUM to a Chromium binary to use it instead of the one Playwright installs.
"""

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto((HERE / "og.html").as_uri())
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(HERE.parent / "site" / "assets" / "og.png"))
    browser.close()
