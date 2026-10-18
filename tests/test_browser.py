"""Headless-browser tests for the interactive layer.

Skipped unless playwright is importable, e.g.:

    uv run --with playwright pytest -m browser
"""
import pathlib
import subprocess
import sys
import time
import urllib.request

import pytest

pw = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

CHROME_CANDIDATES = ["/snap/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"]


@pytest.fixture(scope="module")
def server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "stretchserve", "serve", "docs", "--host", "127.0.0.1", "--port", "8399"],
        cwd=str(pathlib.Path(__file__).resolve().parents[1]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen("http://localhost:8399/", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.fail("server never came up")
    yield "http://localhost:8399"
    proc.terminate()


@pytest.fixture()
def page(server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        kwargs = {"args": ["--no-sandbox"]}
        for path in CHROME_CANDIDATES:
            import os

            if os.path.exists(path):
                kwargs["executable_path"] = path
                break
        browser = p.chromium.launch(**kwargs)
        pg = browser.new_page()
        pg.on("pageerror", lambda e: pytest.fail(f"js page error: {e}"))
        pg.goto(f"{server}/demo.md")
        pg.wait_for_timeout(1500)  # let mermaid/viz draw
        yield pg
        browser.close()


def test_stretches_present_and_closed_by_default(page):
    assert page.locator(".stx").count() >= 8
    assert not page.locator(".stx").first.locator(":scope > .stx-long").is_visible()


def test_click_grows_and_close_button_shrinks(page):
    first = page.locator(".stx").first
    first.locator(":scope > .stx-short").click()
    assert "open" in first.get_attribute("class")
    assert first.locator(":scope > .stx-long").is_visible()
    first.locator(":scope > .stx-long > .stx-close").click()
    assert "open" not in first.get_attribute("class")


def test_nested_stretch(page):
    outer = page.locator(".stx").first
    outer.locator(":scope > .stx-short").click()
    inner = outer.locator(".stx").first
    inner.locator(":scope > .stx-short").click()
    assert "open" in inner.get_attribute("class")
    outer.locator(":scope > .stx-long > .stx-close").click()
    assert not inner.is_visible()


def test_block_stretch_grows_into_list(page):
    block = page.locator(".stx-block")
    assert block.count() == 1
    assert not block.locator(":scope > .stx-long").is_visible()
    block.locator(":scope > .stx-short").click()
    assert block.locator(":scope > .stx-long").is_visible()
    assert block.locator(".stx-long ol li").count() == 3
    block.locator(":scope > .stx-long > .stx-close").click()
    assert "open" not in block.get_attribute("class")


def test_new_words_marked(page):
    page.locator(".stx").first.locator(":scope > .stx-short").click()
    assert page.locator(".stx").first.locator(".stx-new").count() > 0


def test_diagrams_drew(page):
    assert page.locator("svg").count() >= 1
    assert page.locator("pre > code.language-mermaid, div.language-mermaid").count() == 0


def test_short_forms_focusable(page):
    assert page.locator('.stx-short[tabindex="0"]').count() > 0
