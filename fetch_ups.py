from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    Stealth().apply_stealth_sync(page)
    try:
        page.goto('https://www.ups.com/track?loc=en_US&requester=ST/')
        page.wait_for_timeout(5000)
        page.screenshot(path='ups.png', full_page=True)
        with open('ups.html', 'w') as f:
            f.write(page.content())
    finally:
        browser.close()
