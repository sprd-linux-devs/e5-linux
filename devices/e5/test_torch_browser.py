#!/usr/bin/env python3
"""Exercise the real torch app without touching hardware."""
import json
import os
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
APP = HERE / 'infoscreen-torch'
on, fail, delay, available = False, False, 0, True
calls = []
SDK = (HERE.parent / 'common/infoscreen/base/sdk.js').read_bytes()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def log_message(self, *args):
        pass

    def translate_path(self, path):
        if urlsplit(path).path.startswith('/plugins/torch/'):
            path = '/' + path.split('/plugins/torch/', 1)[1]
        return super().translate_path(path)

    def send(self, data, kind='application/json'):
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/host.html':
            return self.send(b'''<!doctype html><html><body class="desktop-wallpaper" data-theme="dark"
 style="margin:0;--bg:#0c121b;--text:#f1f5fa;--dim:#96a5b9;--accent:#85ebcd;--poor:#f0625a;
 --surface-rgb:24,33,46;--button-rgb:35,50,70;--ui-scale:1;--surface-alpha:.7;--wallpaper-wash:linear-gradient(#0c121b33,#0c121b55);
 --desktop-wallpaper:linear-gradient(145deg,#18233d,#086b6e,#b49a59)">
 <iframe id="app" style="position:absolute;left:0;top:44px;width:320px;height:384px;border:0"
 src="/plugins/torch/index.html?lang=zh"></iframe></body></html>''', 'text/html')
        if path == '/sdk/e5.js':
            return self.send(SDK, 'text/javascript')
        if path == '/api/plugins/torch/state':
            calls.append('read')
            return self.send(json.dumps({'ok': available, 'available': available,
                                        'on': on if available else None,
                                        'error': None if available else 'unavailable'}).encode())
        return super().do_GET()

    def do_POST(self):
        global on
        assert self.path == '/api/plugins/torch/toggle'
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        calls.append('toggle')
        if delay:
            time.sleep(delay)
        on = not on
        if fail:
            self.send_response(504)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            return self.wfile.write(b'{"error":"timeout"}')
        self.send(json.dumps({'ok': True, 'available': True, 'on': on}).encode())


def main():
    global on, fail, delay, available
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            chrome = Path(os.environ.get('CHROME_BIN', 'C:/Program Files/Google/Chrome/Application/chrome.exe'))
            with p.chromium.launch(**({'executable_path':str(chrome)} if chrome.exists() else {})) as browser:
                page = browser.new_page(viewport={'width':320, 'height':370}, has_touch=True)
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.set_default_timeout(8000)
                url = f'http://127.0.0.1:{server.server_port}/plugins/torch/index.html?lang=zh'
                page.goto(url)
                switch = page.locator('#switch')
                page.wait_for_function("!document.getElementById('switch').disabled")
                assert page.locator('#state').inner_text() == '已关闭'
                assert calls == ['read']
                switch.tap()
                page.wait_for_function("document.getElementById('switch').getAttribute('aria-pressed') === 'true'")
                assert page.locator('#state').inner_text() == '已开启'
                # Closing/reopening reads hardware; the app does not retain its own state.
                page.goto('about:blank')
                on = False
                page.goto(url)
                page.wait_for_function("!document.getElementById('switch').disabled")
                assert switch.get_attribute('aria-pressed') == 'false'
                # Backend toggles current hardware, even if changed outside this page.
                on = True
                switch.tap()
                page.wait_for_function("!document.getElementById('switch').disabled")
                assert on is False and switch.get_attribute('aria-pressed') == 'false'
                # Slow request: no duplicate writes from multiple clicks or OK-key repeats.
                delay = .4
                before = calls.count('toggle')
                page.evaluate("document.getElementById('switch').click();document.getElementById('switch').click()")
                page.wait_for_function("!document.getElementById('switch').disabled")
                assert calls.count('toggle') == before + 1
                delay = 0
                # Response lost after the write: exactly one POST, then read-only resync.
                fail = True
                before = calls.count('toggle')
                switch.tap()
                page.wait_for_function("!document.getElementById('retry').hidden")
                assert calls.count('toggle') == before + 1
                assert switch.get_attribute('aria-pressed') == str(on).lower()
                assert calls[-2:] == ['toggle', 'read']
                fail = False
                page.locator('#retry').tap()
                page.wait_for_function("document.getElementById('retry').hidden")
                # Missing driver: disabled switch and an explicit read-only retry.
                available = False
                page.reload()
                page.wait_for_function("!document.getElementById('retry').hidden")
                assert switch.is_disabled()
                assert switch.get_attribute('aria-pressed') == 'mixed'
                assert page.locator('#error').inner_text() == '手电筒驱动未就绪'
                available, on = True, True
                page.locator('#retry').tap()
                page.wait_for_function("!document.getElementById('switch').disabled")
                assert switch.get_attribute('aria-pressed') == 'true'
                # Language update does not touch hardware or reset state.
                before = len(calls)
                page.evaluate("window.postMessage({e5:'hello',lang:'tr'},'*')")
                page.wait_for_function("document.documentElement.lang === 'tr'")
                assert page.locator('#state').inner_text() == 'Açık'
                assert len(calls) == before
                # No background polling, overflow or JS exceptions.
                page.wait_for_timeout(1200)
                assert len(calls) == before
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors, errors
                # Real iframe geometry, parent wallpaper/theme and readable large text.
                page.set_viewport_size({'width':320, 'height':480})
                on = False
                page.goto(f'http://127.0.0.1:{server.server_port}/host.html')
                frame = page.frame_locator('#app')
                frame.locator('#switch:not([disabled])').wait_for()
                assert frame.locator('html').get_attribute('class') == 'desktop-wallpaper'
                assert frame.locator('html').evaluate("node => getComputedStyle(node).getPropertyValue('--wallpaper-offset').trim()") == '-44px'
                screenshots = HERE.parents[1] / 'work/e5-camera-20261116/torch-screen'
                screenshots.mkdir(parents=True, exist_ok=True)
                page.locator('#app').screenshot(path=str(screenshots / 'torch-off.png'))
                frame.locator('#switch').tap()
                frame.locator('#switch[aria-pressed="true"]:not([disabled])').wait_for()
                page.locator('#app').screenshot(path=str(screenshots / 'torch-on.png'))
                page.evaluate("document.body.dataset.theme='light';document.body.style.setProperty('--bg','#edf2f7');document.body.style.setProperty('--surface-rgb','255,255,255');document.body.style.setProperty('--wallpaper-wash','linear-gradient(#ffffff26,#ffffff40)');document.body.style.setProperty('--text','#14213a');document.body.style.setProperty('--dim','#506073');document.body.style.setProperty('--accent','#076b63');document.body.style.setProperty('--ui-scale','1.4')")
                frame.locator('html[data-theme="light"]').wait_for()
                assert frame.locator('body').evaluate('node => node.scrollWidth <= innerWidth')
                page.wait_for_timeout(180)  # Finish the theme's color transition before capture.
                page.locator('#app').screenshot(path=str(screenshots / 'torch-light-large.png'))
                assert not errors, errors
                print('PASS: real SDK/app, reentry, hardware toggle, duplicate taps, timeout resync, unavailable/retry and i18n')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
