"""Small, dependency-free Chrome DevTools transport for installed browsers.

Only an application-owned browser with a fresh temporary profile is controlled.
The transport implements the subset used by engine.py; Playwright is optional.
"""

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


def find_browser(choice="auto"):
    roots = [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
             os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    names = {"chrome": ["Google/Chrome/Application/chrome.exe"],
             "msedge": ["Microsoft/Edge/Application/msedge.exe"],
             "chromium": ["Chromium/Application/chrome.exe"]}
    commands = {"chrome": ["google-chrome", "google-chrome-stable"],
                "msedge": ["microsoft-edge", "microsoft-edge-stable"],
                "chromium": ["chromium", "chromium-browser"]}
    choices = ["chrome", "msedge", "chromium"] if choice == "auto" else [choice]
    for name in choices:
        for root in roots:
            for relative in names.get(name, []):
                candidate = Path(root) / relative
                if candidate.is_file():
                    return str(candidate)
        for command in commands.get(name, []):
            candidate = shutil.which(command)
            if candidate:
                return candidate
        if sys.platform == "darwin":
            app = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", "chromium": "Chromium"}[name]
            candidate = Path(f"/Applications/{app}.app/Contents/MacOS/{app}")
            if candidate.is_file():
                return str(candidate)
    raise RuntimeError("설치된 Chrome 또는 Edge를 찾을 수 없습니다. 브라우저를 설치하고 다시 실행하세요.")


class CDPError(RuntimeError):
    pass


class Connection:
    def __init__(self):
        self.pending = {}
        self.counter = 0
        self.tasks = set()
        self.handler = None
        self.reader_task = None
        self.writer = None
        self.last_error = ""
        self.lock = asyncio.Lock()

    async def connect(self, url):
        parts = urlsplit(url)
        if parts.scheme != "ws" or parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise CDPError("DevTools 연결은 로컬 브라우저만 허용합니다.")
        self.reader, self.writer = await asyncio.open_connection(parts.hostname, parts.port)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (f"GET {parts.path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
                   f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n")
        self.writer.write(request.encode("ascii"))
        await self.writer.drain()
        headers = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), 5)
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if b" 101 " not in headers.split(b"\r\n", 1)[0] or accept not in headers:
            raise CDPError("Chrome DevTools WebSocket 연결이 거부되었습니다.")
        self.reader_task = asyncio.create_task(self._read())

    async def _send_frame(self, payload, opcode=1):
        length = len(payload)
        frame = bytes([0x80 | opcode])
        if length < 126:
            frame += bytes([0x80 | length])
        elif length < 65536:
            frame += bytes([0xFE]) + struct.pack("!H", length)
        else:
            frame += bytes([0xFF]) + struct.pack("!Q", length)
        mask = os.urandom(4)
        frame += mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        async with self.lock:
            self.writer.write(frame)
            await self.writer.drain()

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def finished(completed):
            self.tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()  # Navigation can invalidate in-flight events.

        task.add_done_callback(finished)

    async def _read(self):
        fragments = bytearray()
        try:
            while True:
                first, second = await self.reader.readexactly(2)
                opcode = first & 0x0F
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack("!H", await self.reader.readexactly(2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", await self.reader.readexactly(8))[0]
                if length > 64 * 1024 * 1024:
                    raise CDPError("DevTools 응답 크기가 한도를 초과했습니다.")
                mask = await self.reader.readexactly(4) if second & 0x80 else None
                payload = await self.reader.readexactly(length)
                if mask:
                    payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
                if opcode == 8:
                    self.last_error = f"WebSocket close: {payload!r}"
                    break
                if opcode == 9:
                    await self._send_frame(payload, 10)
                    continue
                if opcode == 10:
                    continue
                fragments.extend(payload)
                if not first & 0x80:
                    continue
                message = json.loads(fragments.decode("utf-8"))
                fragments.clear()
                future = self.pending.pop(message.get("id"), None)
                if future is not None and not future.done():
                    if "error" in message:
                        future.set_exception(CDPError(message["error"].get("message", "DevTools error")))
                    else:
                        future.set_result(message.get("result", {}))
                elif self.handler and "method" in message:
                    self.spawn(self.handler(message))
        except (OSError, asyncio.IncompleteReadError, ValueError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(CDPError(f"브라우저 연결이 닫혔습니다. {self.last_error}"))
            self.pending.clear()

    async def send(self, method, params=None, session=None, timeout=15):
        self.counter += 1
        identifier = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[identifier] = future
        message = {"id": identifier, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            await self._send_frame(json.dumps(message).encode("utf-8"))
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(identifier, None)

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


class Browser:
    def __init__(self):
        self.connection = Connection()
        self.connection.handler = self.event
        self.context = None
        self.process = None
        self.profile = None
        self.error_log = None
        self.stderr_text = ""

    @classmethod
    async def launch(cls, choice="auto", headless=False):
        browser = cls()
        executable = find_browser(choice)
        browser.profile = tempfile.TemporaryDirectory(prefix="ffgraber-")
        arguments = [executable, f"--user-data-dir={browser.profile.name}",
                     "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
                     "--no-first-run", "--no-default-browser-check", "about:blank"]
        if headless:
            arguments.insert(1, "--headless=new")
        try:
            browser.error_log = tempfile.TemporaryFile()
            browser.process = subprocess.Popen(arguments, stdout=subprocess.DEVNULL, stderr=browser.error_log)
            port_file = Path(browser.profile.name) / "DevToolsActivePort"
            for _ in range(150):
                if browser.process.poll() is not None:
                    raise CDPError("브라우저가 시작 직후 종료되었습니다.")
                try:
                    lines = port_file.read_text(encoding="utf-8").splitlines()
                    if len(lines) >= 2:
                        await browser.connection.connect(f"ws://127.0.0.1:{int(lines[0])}{lines[1]}")
                        return browser
                except (FileNotFoundError, ValueError):
                    pass
                await asyncio.sleep(0.1)
            raise CDPError("브라우저의 DevTools 준비 시간이 초과되었습니다.")
        except BaseException:
            await browser.close()
            raise

    async def new_context(self, **kwargs):
        # The entire browser already owns a fresh profile. A second incognito
        # context is unnecessary and can be disabled by enterprise policy.
        self.context = Context(self, None)
        await self.connection.send("Target.setAutoAttach", {
            "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True,
            "filter": [{"type": "page", "exclude": False}, {"exclude": True}],
        })
        return self.context

    async def event(self, message):
        if self.context:
            await self.context.event(message)

    async def close(self):
        if self.connection.writer:
            try:
                await self.connection.send("Browser.close", timeout=3)
            except Exception:
                pass
        await self.connection.close()
        if self.process and self.process.poll() is None:
            try:
                await asyncio.to_thread(self.process.wait, 3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    await asyncio.to_thread(self.process.wait, 3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        if self.profile:
            # Chrome may hold profile files briefly after its main process exits.
            try:
                self.profile.cleanup()
            except OSError:
                pass
        if self.error_log:
            self.error_log.seek(0)
            self.stderr_text = self.error_log.read().decode("utf-8", errors="replace")[-6000:]
            self.error_log.close()
            self.error_log = None


class Context:
    def __init__(self, browser, identifier):
        self.browser = browser
        self.identifier = identifier
        self.connection = browser.connection
        self.targets = {}
        self.sessions = {}
        self.ready = {}
        self.callbacks = {}
        self.scripts = []
        self.route_handler = None

    @property
    def pages(self):
        return [page for page in self.targets.values() if not page.closed]

    def on(self, event, callback):
        self.callbacks[event] = callback

    async def route(self, pattern, handler):
        self.route_handler = handler

    async def add_init_script(self, script):
        self.scripts.append(script)

    async def new_cdp_session(self, page):
        return self.connection

    async def new_page(self):
        parameters = {"url": "about:blank"}
        if self.identifier:
            parameters["browserContextId"] = self.identifier
        result = await self.connection.send("Target.createTarget", parameters)
        target = result["targetId"]
        ready = self.ready.setdefault(target, asyncio.Event())
        await asyncio.wait_for(ready.wait(), 10)
        page = self.targets[target]
        if page.setup_error:
            raise CDPError(page.setup_error)
        return page

    async def event(self, message):
        method = message["method"]
        params = message.get("params", {})
        if method == "Target.attachedToTarget":
            info = params["targetInfo"]
            session = params["sessionId"]
            if self.identifier and info.get("browserContextId") != self.identifier:
                await self.connection.send("Runtime.runIfWaitingForDebugger", session=session)
                return
            page = Page(self, info["targetId"], session, info.get("url", "about:blank"))
            self.targets[page.identifier] = page
            self.sessions[session] = page
            try:
                await page.command("Page.enable")
                await page.command("Runtime.enable")
                await page.command("Network.enable")
                await page.command("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
                for script in self.scripts:
                    await page.command("Page.addScriptToEvaluateOnNewDocument", {"source": script})
                if "page" in self.callbacks:
                    self.callbacks["page"](page)
                await page.command("Runtime.runIfWaitingForDebugger")
            except Exception as exc:
                page.setup_error = str(exc)
            finally:
                self.ready.setdefault(page.identifier, asyncio.Event()).set()
            return
        page = self.sessions.get(message.get("sessionId"))
        if method == "Target.detachedFromTarget":
            page = self.sessions.get(params.get("sessionId"))
            if page:
                page.closed = True
            return
        if not page:
            return
        if method == "Page.frameNavigated" and not params["frame"].get("parentId"):
            page.url = params["frame"]["url"]
        elif method == "Fetch.requestPaused":
            route = Route(page, params)
            if self.route_handler:
                await self.route_handler(route)
            else:
                await route.continue_()
        elif method == "Network.responseReceived":
            response = params["response"]
            if "response" in self.callbacks:
                self.callbacks["response"](Response(response))
        elif method == "Network.requestWillBeSent" and "redirectResponse" in params:
            if "response" in self.callbacks:
                self.callbacks["response"](Response(params["redirectResponse"]))
        elif method == "Page.javascriptDialogOpening":
            await page.command("Page.handleJavaScriptDialog", {"accept": False})


class Response:
    def __init__(self, response):
        self.url = response["url"]
        self.status = response.get("status", 200)
        self.headers = {name.lower(): str(value) for name, value in response.get("headers", {}).items()}

    async def all_headers(self):
        return self.headers


class Route:
    def __init__(self, page, params):
        self.page = page
        self.identifier = params["requestId"]
        self.request = Request(params["request"]["url"])

    async def abort(self):
        await self.page.command("Fetch.failRequest", {"requestId": self.identifier, "errorReason": "Aborted"})

    async def continue_(self):
        await self.page.command("Fetch.continueRequest", {"requestId": self.identifier})


class Request:
    def __init__(self, url):
        self.url = url


class Page:
    def __init__(self, context, identifier, session, url):
        self.context = context
        self.identifier = identifier
        self.session = session
        self.url = url
        self.closed = False
        self.setup_error = ""

    async def command(self, method, params=None):
        return await self.context.connection.send(method, params, self.session)

    def set_default_timeout(self, timeout):
        pass

    def on(self, event, handler):
        pass  # Downloads are denied globally; dialogs are dismissed in Context.

    def is_closed(self):
        return self.closed

    async def goto(self, url, **kwargs):
        result = await self.command("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise CDPError(result["errorText"])
        # Give DOMContentLoaded a chance without waiting on large ad resources.
        for _ in range(80):
            try:
                state = await self.evaluate("() => ({ready:document.readyState !== 'loading',url:location.href})")
                if state["url"] != "about:blank":
                    self.url = state["url"]
                if state["ready"] and state["url"] != "about:blank":
                    break
            except CDPError:
                pass
            await asyncio.sleep(0.1)
        return None

    async def evaluate(self, function):
        result = await self.command("Runtime.evaluate", {
            "expression": f"({function})()", "returnByValue": True, "awaitPromise": True,
            "timeout": 5000,
        })
        if "exceptionDetails" in result:
            raise CDPError(result["exceptionDetails"].get("text", "JavaScript evaluation failed"))
        return result.get("result", {}).get("value")

    def locator(self, selector):
        return Locator(self, selector)

    async def close(self):
        if not self.closed:
            try:
                await self.context.connection.send("Target.closeTarget", {"targetId": self.identifier})
            finally:
                self.closed = True


class Locator:
    def __init__(self, page, selector, index=0):
        self.page = page
        self.selector = selector
        self.index = index

    def nth(self, index):
        return Locator(self.page, self.selector, index)

    def element(self):
        return f"document.querySelectorAll({json.dumps(self.selector)})[{self.index}]"

    async def count(self):
        return await self.page.evaluate(f"() => document.querySelectorAll({json.dumps(self.selector)}).length")

    async def is_visible(self):
        return await self.page.evaluate(f"() => {{ const e={self.element()}; return !!e && !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'; }}")

    async def is_enabled(self):
        return await self.page.evaluate(f"() => {{ const e={self.element()}; return !!e && !e.disabled && e.getAttribute('aria-disabled') !== 'true'; }}")

    async def evaluate(self, function):
        return await self.page.evaluate(f"() => ({function})({self.element()})")

    async def click(self, **kwargs):
        point = await self.page.evaluate(f"() => {{ const e={self.element()}; if(!e) return null; e.scrollIntoView({{block:'center'}}); const r=e.getBoundingClientRect(); return {{x:r.x+r.width/2,y:r.y+r.height/2}}; }}")
        if point:
            await self.page.command("Input.dispatchMouseEvent", {"type": "mousePressed", "button": "left", "clickCount": 1, **point})
            await self.page.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "button": "left", "clickCount": 1, **point})
