from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    context = browser.new_context()

    page = context.new_page()

    page.goto("https://purdue.brightspace.com")

    print("Log in to Brightspace with Purdue SSO + 2FA.")

    input("After you are fully logged in and on the course page, press ENTER...")

    context.storage_state(path="brightspace_auth.json")

    print("Login session saved to brightspace_auth.json")

    browser.close()
