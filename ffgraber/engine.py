"""A sequential browser worker. All GUI communication uses immutable events."""

import asyncio
from collections import deque
from dataclasses import asdict, dataclass
import threading
import time
from urllib.parse import urlsplit

from .links import Candidate, FILECRYPT_HOSTS, discover, display_name, kind_of, normalize_url, url_key
from .i18n import translate
from .models import Record


@dataclass(frozen=True)
class Options:
    backend: str = "auto"
    browser: str = "auto"
    resolve_direct: bool = True
    timeout: float = 180
    max_pages: int = 1500
    max_depth: int = 8
    headless: bool = False
    language: str = "ko"


# Installed before page scripts run, including after navigation. Only a known
# download host is intercepted; Filecrypt's window.open continues to work.
CAPTURE_SCRIPT = r"""(() => {
    window.__ffgraberUrls = [];
    const originalOpen = window.open;
    window.open = function(url, ...args) {
        try {
            const target = new URL(url, location.href);
            if (/^dl\d*\.fuckingfast\.co$/i.test(target.hostname)) {
                window.__ffgraberUrls.push(target.href);
                return null;
            }
        } catch (_) {}
        return originalOpen.call(this, url, ...args);
    };
})();"""

SNAPSHOT_SCRIPT = r"""() => ({
    html: document.documentElement?.outerHTML || '',
    text: document.body?.innerText || '',
    captured: window.__ffgraberUrls || [],
    gated: !!document.querySelector('input[type=password], #captcha, .g-recaptcha, .cf-turnstile, #challenge-running, #cutcaptcha, #pow-captcha, #cform'),
    title: document.title
})"""

FF_BUTTONS = 'a[hx-post], button[hx-post], #download-btn, #download, button.download, a.download'


class ExtractionEngine:
    def __init__(self, options=None, emit=None, cancel=None, skip=None):
        self.options = options or Options()
        self.emit = emit or (lambda event: None)
        self.cancel = cancel or threading.Event()
        self.skip = skip or threading.Event()
        self.records: dict[str, Record] = {}
        self.context = None
        self._captured = {}
        self._background = set()

    def update(self, record, **changes):
        if changes.get("error"):
            changes["error"] = translate(changes["error"], self.options.language)
        for key, value in changes.items():
            setattr(record, key, value)
        self.emit({"type": "record", "record": asdict(record)})

    def log(self, message):
        self.emit({"type": "log", "message": translate(message, self.options.language)})

    def _capture(self, value, base=""):
        try:
            url = normalize_url(value, base)
            if kind_of(url) == "direct":
                self._captured.setdefault(url, None)
        except ValueError:
            pass

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _route(self, route):
        if kind_of(route.request.url) == "direct":
            self._capture(route.request.url)
            await route.abort()  # Never request the file payload.
        else:
            await route.continue_()

    async def _response(self, response):
        try:
            # Headers can expose the final URL without navigating to the payload.
            if kind_of(response.url) not in {"ff", "filecrypt-link", "filecrypt", "direct"}:
                return
            headers = await response.all_headers()
            for name in ("hx-redirect", "location"):
                if headers.get(name):
                    self._capture(headers[name], response.url)
        except Exception:
            # Responses may disappear when a popup is closed or navigation ends.
            return

    async def _download(self, download):
        self._capture(download.url)
        try:
            await download.cancel()
        except Exception:
            pass

    def _configure_page(self, page):
        page.set_default_timeout(1500)
        page.on("download", lambda download: self._spawn(self._download(download)))
        page.on("dialog", lambda dialog: self._spawn(dialog.dismiss()))

    async def _launch(self, playwright):
        choices = ["chrome", "msedge", "chromium"] if self.options.browser == "auto" else [self.options.browser]
        failures = []
        for choice in choices:
            try:
                kwargs = {"headless": self.options.headless}
                if choice != "chromium":
                    kwargs["channel"] = choice
                browser = await playwright.chromium.launch(**kwargs)
                self.log(f"브라우저 시작: {choice}")
                return browser
            except Exception as exc:
                failures.append(f"{choice}: {str(exc).splitlines()[0]}")
        raise RuntimeError(
            "브라우저를 시작할 수 없습니다. Chrome 또는 Edge를 설치하거나 "
            "install_browser.bat을 실행해 Chromium을 설치하세요.\n" + "\n".join(failures)
        )

    async def run(self, urls):
        """Create a private session, process a bounded queue, retain partial results."""
        if self.options.backend == "reference":
            from .reference import ReferenceRunner
            return await ReferenceRunner(self).run(urls)
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            from .cdp import Browser
            browser = await Browser.launch(self.options.browser, self.options.headless)
            self.log("설치된 브라우저로 시작했습니다. 별도 패키지 설치가 필요하지 않습니다.")
            return await self._run_browser(browser, urls)

        async with async_playwright() as playwright:
            browser = await self._launch(playwright)
            return await self._run_browser(browser, urls)

    async def _run_browser(self, browser, urls):
        try:
            self.context = await browser.new_context(accept_downloads=False, service_workers="block")
            self.context.on("page", self._configure_page)
            self.context.on("response", lambda response: self._spawn(self._response(response)))
            await self.context.route("**/*", self._route)
            await self.context.add_init_script(CAPTURE_SCRIPT)
            # Denial also covers downloads that bypass ordinary HTTP routing.
            guard_page = await self.context.new_page()
            cdp = await self.context.new_cdp_session(guard_page)
            await cdp.send("Browser.setDownloadBehavior", {"behavior": "deny"})
            return await self.process(urls)
        finally:
            for task in list(self._background):
                task.cancel()
            if self._background:
                await asyncio.gather(*list(self._background), return_exceptions=True)
            await browser.close()

    async def process(self, urls):
        queue = deque()

        def enqueue(candidate, source="", depth=0):
            url = normalize_url(candidate.url)
            key = url_key(url)
            if key in self.records:
                return
            record = Record(url=url, source=source, name=candidate.name or display_name(url),
                            kind=kind_of(url), depth=depth, expected_host=candidate.expected_host)
            self.records[key] = record
            if depth > self.options.max_depth or len(self.records) > self.options.max_pages:
                self.update(record, status="failed", error="탐색 한도에 도달했습니다. 이 URL로 별도 추출하세요.")
                return
            self.update(record)
            queue.append(record)

        for url in urls:
            enqueue(Candidate(url))
        while queue:
            if self.cancel.is_set():
                break
            record = queue.popleft()
            self.skip.clear()
            if record.kind == "direct":
                self.update(record, status="done", direct_url=record.url)
                continue
            if record.kind == "ff" and not self.options.resolve_direct:
                self.update(record, status="found")
                continue
            self.update(record, status="running", error="")
            try:
                children, targets = await self._visit_cancellable(record)
                if targets:
                    target = targets[0]
                    changes = {"direct_url": target} if kind_of(target) == "direct" else {"resolved_url": target}
                    self.update(record, status="done", **changes)
                    for extra in targets[1:]:
                        enqueue(Candidate(extra), record.url, record.depth + 1)
                else:
                    self.update(record, status="scanned")
                for child in children:
                    enqueue(child, record.url, record.depth + 1)
            except asyncio.CancelledError:
                self.update(record, status="cancelled", error="사용자가 중지했습니다.")
                break
            except Skipped:
                self.update(record, status="skipped", error="사용자가 건너뛰었습니다.")
            except Exception as exc:
                self.update(record, status="failed", error=str(exc))
                self.log(f"실패: {record.name} — {exc}")
            self.emit({"type": "progress", "remaining": len(queue), "total": len(self.records)})
        for record in queue:
            self.update(record, status="cancelled", error="사용자가 중지했습니다.")
        return list(self.records.values())

    async def _visit_cancellable(self, record):
        task = asyncio.create_task(self._visit(record))
        try:
            while not task.done():
                if self.cancel.is_set():
                    raise asyncio.CancelledError()
                if self.skip.is_set():
                    raise Skipped()
                await asyncio.sleep(0.1)
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _visit(self, record):
        # A separate tab per task avoids state leaking between parts. Container
        # cookies remain in the context for the following /Link/ tasks.
        before = set(self.context.pages)
        page = await self.context.new_page()
        self._captured = {}
        children = {}
        try:
            self.log(f"열기: {record.url}")
            try:
                response = await page.goto(record.url, wait_until="domcontentloaded", timeout=20000)
                if response and response.status in {404, 410}:
                    raise RuntimeError(f"링크가 삭제되었거나 없습니다. (HTTP {response.status})")
            except Exception as exc:
                if "Timeout" not in type(exc).__name__ and not self._captured:
                    # Download navigations are intentionally aborted by routing.
                    if "ERR_ABORTED" not in str(exc) and "ERR_FAILED" not in str(exc):
                        raise
            started = time.monotonic()
            last_change = started
            last_click = 0.0
            warned = False
            while time.monotonic() - started < self.options.timeout:
                if self._captured:
                    return list(children.values()), list(self._captured)
                live_pages = [p for p in self.context.pages if p not in before and not p.is_closed()]
                if not live_pages:
                    raise RuntimeError("브라우저 탭이 닫혔습니다. 다시 추출하세요.")
                for current in live_pages:
                    current_kind = kind_of(current.url)
                    if current_kind == "direct":
                        self._capture(current.url)
                        continue
                    if current_kind == "ff" and record.kind != "ff":
                        child = Candidate(current.url)
                        children.setdefault(url_key(child.url), child)
                        continue
                    if record.kind == "filecrypt-link" and current_kind == "page" and current.url != "about:blank":
                        parts = urlsplit(current.url)
                        host = (parts.hostname or "").lower()
                        matches = not record.expected_host or host == record.expected_host or host.endswith("." + record.expected_host)
                        if (host.removeprefix("www.") in FILECRYPT_HOSTS and
                                parts.path.lower().endswith("/404.html")):
                            raise RuntimeError("Filecrypt 개별 링크가 삭제되었거나 없습니다.")
                        if matches and host.removeprefix("www.") not in FILECRYPT_HOSTS and parts.scheme in {"http", "https"} and host not in {
                            "friendlyduck.com", "www.friendlyduck.com", "powerusenet.xyz", "www.powerusenet.xyz",
                        } and "usenet" not in parts.path.lower():
                            return list(children.values()), [normalize_url(current.url)]
                    if current != page and current_kind == "page":
                        # Unrelated popup ads must not become crawl inputs.
                        if current.url != "about:blank":
                            await current.close()
                        continue
                    try:
                        snapshot = await current.evaluate(SNAPSHOT_SCRIPT)
                    except Exception:
                        continue  # The tab may be navigating after user verification.
                    for url in snapshot["captured"]:
                        self._capture(url, current.url)
                    for child in discover(snapshot["html"] + "\n" + snapshot["text"], current.url):
                        if child.url and url_key(child.url) != url_key(record.url):
                            if kind_of(child.url) == "direct":
                                self._capture(child.url)
                            elif url_key(child.url) not in children:
                                children[url_key(child.url)] = child
                                last_change = time.monotonic()
                    # Only FF file pages get automatic download-button clicks.
                    if current_kind == "ff" and time.monotonic() - last_click >= 3:
                        controls = current.locator(FF_BUTTONS)
                        for index in range(min(await controls.count(), 6)):
                            button = controls.nth(index)
                            if await button.is_visible() and await button.is_enabled():
                                opacity = await button.evaluate("el => getComputedStyle(el).opacity")
                                if float(opacity) <= 0.5:
                                    continue
                                try:
                                    await button.click(timeout=1000, no_wait_after=True)
                                except Exception:
                                    pass
                                last_click = time.monotonic()
                                break
                    if not warned and (snapshot["gated"] or time.monotonic() - started >= 8):
                        self.update(record, status="waiting")
                        self.log("인증/비밀번호/추가 버튼이 있으면 열린 브라우저에서 처리하세요. 자동 감지 후 계속합니다.")
                        warned = True
                if self._captured:
                    return list(children.values()), list(self._captured)
                if children and time.monotonic() - last_change >= 1.2:
                    return list(children.values()), []
                await asyncio.sleep(0.25)
            raise RuntimeError(f"{self.options.timeout:g}초 동안 링크를 찾지 못했습니다. 인증·비밀번호·사이트 상태를 확인하세요.")
        finally:
            # Drain response-header callbacks before the next record resets capture.
            if self._background:
                pending = list(self._background)
                done, pending = await asyncio.wait(pending, timeout=1)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    if not task.cancelled():
                        task.exception()
            for tab in list(self.context.pages):
                if tab not in before and not tab.is_closed():
                    await tab.close()


class Skipped(Exception):
    pass
