"""Real-browser UI test (Playwright + headless Chromium) against the live app."""

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.needs_redis, pytest.mark.e2e]


@pytest.fixture
def page(live_server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.base = live_server()
        yield page
        browser.close()


def test_shorten_through_the_ui_and_follow_link(page):
    page.goto(page.base)
    page.fill("#urlInput", f"{page.base}/health")  # a real, reachable target
    page.click("text=Shorten URL")
    link = page.locator("#shortUrlLink")
    link.wait_for(state="visible")
    short_url = link.text_content()
    assert short_url.startswith(page.base + "/")
    # Following the short link must land on the target (the health JSON).
    page.goto(short_url)
    assert '"status"' in page.content()


def test_custom_alias_and_expiry_through_the_ui(page):
    page.goto(page.base)
    page.fill("#urlInput", f"{page.base}/health")
    page.fill("#aliasInput", "ui-alias")
    page.select_option("#expiryInput", "3600")
    page.click("text=Shorten URL")
    page.locator("#shortUrlLink").wait_for(state="visible")
    assert page.locator("#shortUrlLink").text_content().endswith("/ui-alias")
    assert "expires_at" in page.locator("#jsonResult").text_content()
    assert '"expires_at": null' not in page.locator("#jsonResult").text_content()


def test_taken_alias_shows_error_dialog(page):
    page.goto(page.base)
    messages = []
    page.on("dialog", lambda d: (messages.append(d.message), d.accept()))
    for _ in range(2):
        page.fill("#urlInput", f"{page.base}/health")
        page.fill("#aliasInput", "dup-alias")
        page.click("text=Shorten URL")
        page.wait_for_timeout(500)
    assert any("409" in m and "already taken" in m.lower() for m in messages), messages
