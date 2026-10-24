"""FuckingFast-only worker following the supplied extractor's verified flow."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import re
import time
from urllib.parse import urlsplit

from .cdp import find_browser
from .links import discover, display_name, kind_of, normalize_url, url_key
from .models import Record


INSTALL_SCRIPT = r"""(() => {
    const capture = value => {
        if (!value) return false;
        try {
            const url = new URL(value, location.href);
            if (!/^dl\d*\.fuckingfast\.co$/i.test(url.hostname)) return false;
            document.documentElement.setAttribute('data-direct-url', url.href);
            if (document.body) document.body.setAttribute('data-direct-url', url.href);
            return true;
        } catch (_) { return false; }
    };
    window.open = function(url) { capture(url); return null; };
    if (!window.__ffgraberXhrInstalled) {
        window.__ffgraberXhrInstalled = true;
        const OriginalXHR = window.XMLHttpRequest;
        function InterceptedXHR() {
            const xhr = new OriginalXHR();
            xhr.addEventListener('readystatechange', function() {
                if (xhr.readyState === 4) {
                    capture(xhr.getResponseHeader('hx-redirect') || xhr.getResponseHeader('location'));
                }
            });
            return xhr;
        }
        InterceptedXHR.prototype = OriginalXHR.prototype;
        Object.setPrototypeOf(InterceptedXHR, OriginalXHR);
        window.XMLHttpRequest = InterceptedXHR;
        // HTMX emits this before handling HX-Redirect. Prevent the file request
        // after recording its URL. Browser-level download denial remains active.
        document.addEventListener('htmx:beforeOnLoad', function(event) {
            const xhr = event.detail && event.detail.xhr;
            if (xhr && capture(xhr.getResponseHeader('hx-redirect') || xhr.getResponseHeader('location'))) {
                event.preventDefault();
            }
        });
    }
})();"""

CLICK_SCRIPT = r"""
let found = document.documentElement.getAttribute('data-direct-url') ||
            (document.body && document.body.getAttribute('data-direct-url'));
if (found) return found;
const button = document.querySelector('a[hx-post], button[hx-post], #download-btn, a.download, button.download');
if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true' &&
    Number(getComputedStyle(button).opacity) > 0.5 && button.getClientRects().length) {
    button.click();
}
return document.documentElement.getAttribute('data-direct-url') ||
       (document.body && document.body.getAttribute('data-direct-url'));
"""


def validate_ff_urls(urls):
    result = {}
    for value in urls:
        url = normalize_url(value)
        if kind_of(url) not in {"ff", "direct"}:
            raise ValueError(f"FuckingFast URL만 입력하세요: {value}")
        if kind_of(url) == "ff" and urlsplit(url).path in {"", "/"}:
            raise ValueError("FuckingFast 파일 페이지 URL을 입력하세요.")
        result.setdefault(url_key(url), url)
    if not result:
        raise ValueError("추출할 FuckingFast URL을 입력하세요.")
    return list(result.values())


def create_driver(browser):
    # The reference imports setuptools before undetected_chromedriver because
    # Python 3.12+ no longer includes distutils in the standard library.
    try:
        import setuptools  # noqa: F401
        import undetected_chromedriver as uc
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options as EdgeOptions
    except ImportError as exc:
        raise RuntimeError("참고 소스 엔진의 의존성이 없습니다. start.bat을 실행해 requirements.txt를 설치하세요.") from exc
    if browser == "auto":
        try:
            executable = find_browser("chrome")
            browser = "chrome"
        except RuntimeError:
            executable = find_browser("msedge")
            browser = "msedge"
    else:
        executable = find_browser(browser)
    if browser == "msedge":
        options = EdgeOptions()
        options.binary_location = executable
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        return webdriver.Edge(options=options)
    if browser != "chrome":
        raise ValueError("참고 엔진에서는 Chrome 또는 Edge를 선택하세요.")

    def launch(version=None):
        return uc.Chrome(options=uc.ChromeOptions(), use_subprocess=True,
                         browser_executable_path=executable, version_main=version,
                         no_sandbox=False)

    try:
        return launch()
    except Exception as exc:
        match = re.search(r"Current browser version is\s+(\d+)", str(exc), re.I)
        if not match:
            raise
        return launch(int(match.group(1)))


class ReferenceRunner:
    def __init__(self, engine, factory=None):
        self.engine = engine
        self.factory = factory or create_driver
        self.executor = None
        self.driver = None

    async def call(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, partial(function, *args))

    async def run(self, urls):
        engine = self.engine
        urls = validate_ff_urls(urls)
        records = []
        for url in urls:
            record = Record(url=url, name=display_name(url), kind=kind_of(url))
            engine.records[url_key(url)] = record
            engine.update(record)
            records.append(record)
        pending = [record for record in records if record.kind == "ff" and engine.options.resolve_direct]
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ff-reference")
        try:
            for record in records:
                if record.kind == "direct":
                    engine.update(record, status="done", direct_url=record.url)
                elif not engine.options.resolve_direct:
                    engine.update(record, status="found")
            if not pending:
                return records
            if engine.cancel.is_set():
                return records
            engine.log("참고 소스 엔진으로 브라우저 시작 중…")
            self.driver = await self.call(self.factory, engine.options.browser)
            await self.call(self.driver.set_page_load_timeout, 20)
            await self.call(self.driver.set_script_timeout, 5)
            # Fail closed if the browser cannot disable real file downloads.
            await self.call(self.driver.execute_cdp_cmd, "Browser.setDownloadBehavior", {"behavior": "deny"})
            engine.log("브라우저 준비 완료 · 다운로드 차단 활성화")
            for index, record in enumerate(pending):
                if engine.cancel.is_set():
                    break
                engine.skip.clear()
                engine.update(record, status="running", error="")
                engine.log(f"[{index + 1}/{len(pending)}] {record.name}")
                try:
                    direct = await self.resolve(record)
                    if engine.cancel.is_set():
                        engine.update(record, status="cancelled", error="사용자가 중지했습니다.")
                        break
                    if engine.skip.is_set():
                        engine.update(record, status="skipped", error="사용자가 건너뛰었습니다.")
                    elif direct:
                        engine.update(record, status="done", direct_url=direct)
                    else:
                        engine.update(record, status="failed", error="최종 URL을 찾지 못했습니다. 브라우저의 인증·오류 메시지를 확인하세요.")
                except Exception as exc:
                    engine.update(record, status="failed", error=str(exc))
                    engine.log(f"실패: {record.name} — {exc}")
                engine.emit({"type": "progress", "remaining": len(pending) - index - 1, "total": len(records)})
            return records
        except Exception as exc:
            for record in records:
                if record.status in {"queued", "running", "waiting"}:
                    engine.update(record, status="failed", error=str(exc))
            raise
        finally:
            for record in records:
                if record.status in {"queued", "running", "waiting"}:
                    engine.update(record, status="cancelled", error="사용자가 중지했습니다.")
            if self.driver:
                try:
                    await self.call(self.driver.quit)
                except Exception:
                    pass
            self.executor.shutdown(wait=False, cancel_futures=True)

    async def resolve(self, record):
        engine = self.engine
        try:
            await self.call(self.driver.get, record.url)
        except Exception as exc:
            if type(exc).__name__ != "TimeoutException":
                raise
        await self.call(self.driver.execute_script, INSTALL_SCRIPT)
        deadline = time.monotonic() + engine.options.timeout
        warned = False
        while time.monotonic() < deadline:
            if engine.cancel.is_set() or engine.skip.is_set():
                return ""
            candidate = await self.call(self.driver.execute_script, CLICK_SCRIPT)
            if candidate and kind_of(str(candidate)) == "direct":
                return normalize_url(str(candidate))
            current = await self.call(lambda: self.driver.current_url)
            if kind_of(current) == "direct":
                return normalize_url(current)
            html = await self.call(lambda: self.driver.page_source)
            for candidate in discover(html, record.url):
                if kind_of(candidate.url) == "direct":
                    return candidate.url
            if not warned and time.monotonic() > deadline - engine.options.timeout + 8:
                engine.update(record, status="waiting")
                engine.log("인증 화면이 있으면 열린 브라우저에서 처리하세요. 자동으로 이어집니다.")
                warned = True
            await asyncio.sleep(1)
        return ""
