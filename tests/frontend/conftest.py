"""Browser tests of the Optima frontend (Playwright + Chromium).

Skipped when Playwright or a Chromium build is not available, so the default test run is
unchanged on machines without them. Install: ``pip install playwright`` and
``playwright install chromium`` (or set OPTIMA_CHROMIUM to an existing Chromium binary).
The tests start the real API (api.app) on a free local port; outside requests (CDNs) are
blocked, so nothing leaves the machine.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: frontend tests in a headless browser")


@pytest.fixture(scope="session")
def api_server():
    uvicorn = pytest.importorskip("uvicorn")
    from api.app import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("OPTIMA_CHROMIUM") or (
        "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(executable_path=executable)
        except Exception as exc:  # noqa: BLE001 - no browser build available
            pytest.skip(f"Chromium not available for Playwright: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser, api_server):
    pg = browser.new_page(viewport={"width": 1500, "height": 1000})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(api_server)
             else r.abort())
    pg.goto(api_server + "/")
    pg.evaluate("$('login-user').value='admin'; $('login-pass').value='optima123'; handleLogin()")
    pg.page_errors = errors
    yield pg
    pg.close()
