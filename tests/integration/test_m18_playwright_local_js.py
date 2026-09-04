from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.browser_acquisition.probe import probe_js_link_discovery

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER") != "1",
    reason="set RUN_BROWSER=1 after installing Playwright Chromium",
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"""<!doctype html>
<html><body>
<div id='links'></div>
<script>
document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    document.getElementById('links').innerHTML =
      '<a href="/dynamic-one">one</a><a href="/dynamic-two">two</a>';
  }, 50);
});
</script>
</body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def test_m18_playwright_observes_links_not_present_in_initial_html():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        result = probe_js_link_discovery(
            f"http://{host}:{port}/",
            settle_ms=250,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert "/dynamic-one" not in result.initial_hrefs
    assert "/dynamic-two" not in result.initial_hrefs
    assert "/dynamic-one" in result.rendered_hrefs
    assert "/dynamic-two" in result.rendered_hrefs
    assert result.js_added_links is True
