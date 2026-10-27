"""Read browser hyperlinks without changing the user's clipboard."""

import ctypes
from ctypes import wintypes
from html.parser import HTMLParser
import re
import sys

from .links import normalize_url


class _Hyperlinks(HTMLParser):
    def __init__(self, html, selection=None, base=""):
        super().__init__(convert_charrefs=True)
        self.selection = selection or (0, len(html))
        self.base = base
        self.lines = [0] + [match.end() for match in re.finditer("\n", html)]
        self.anchors = []
        self.active = []

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.active.append((self.position(), dict(attrs).get("href")))

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            start, href = self.active.pop()
            self.add(start, self.position(), href)

    def add(self, start, end, href):
        if href and start < self.selection[1] and end > self.selection[0]:
            try:
                url = normalize_url(href, self.base)
                if any(char.isspace() for char in url):
                    return
            except ValueError:
                return
            self.anchors.append((start, url))


def html_links(html, selection=None, base=""):
    """Read hrefs, including a containing anchor around a copied text fragment."""
    parser = _Hyperlinks(html, selection, base)
    parser.feed(html)
    parser.close()
    for start, href in parser.active:
        parser.add(start, len(html), href)
    return list(dict.fromkeys(url for _, url in sorted(parser.anchors)))


def clipboard_html_links(payload):
    """CF_HTML offsets count UTF-8 bytes, not Unicode characters."""
    payload = payload.rstrip(b"\0")
    header = payload[:payload.find(b"<")] if b"<" in payload else payload
    header = header.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    offsets = {key.decode(): int(value) for key, value in re.findall(
        rb"(?m)^(StartHTML|EndHTML|StartFragment|EndFragment):[ \t]*(-?\d{1,12})[ \t]*$", header)}
    start, end = offsets.get("StartHTML", -1), offsets.get("EndHTML", -1)
    if not 0 <= start < end <= len(payload):
        start, end = max(payload.find(b"<"), 0), len(payload)
    fragment_start = offsets.get("StartFragment", -1)
    fragment_end = offsets.get("EndFragment", -1)
    selection = None
    if start <= fragment_start < fragment_end <= end:
        selection = (len(payload[start:fragment_start].decode("utf-8", errors="replace")),
                     len(payload[start:fragment_end].decode("utf-8", errors="replace")))
    else:
        begin = payload.find(b"<!--StartFragment-->", start, end)
        finish = payload.find(b"<!--EndFragment-->", start, end)
        if start <= begin < finish <= end:
            selection = (len(payload[start:begin].decode("utf-8", errors="replace")),
                         len(payload[start:finish].decode("utf-8", errors="replace")))
    source = re.search(rb"(?m)^SourceURL:([^\r\n]+)", header)
    base = source.group(1).decode("utf-8", errors="replace").strip() if source else ""
    return html_links(payload[start:end].decode("utf-8", errors="replace"), selection, base)


def read_html_clipboard():
    """Read Windows HTML Format via pointer-sized handles; return empty on failure."""
    if sys.platform != "win32":
        return b""
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user.RegisterClipboardFormatW.restype = wintypes.UINT
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.OpenClipboard.restype = wintypes.BOOL
    user.CloseClipboard.argtypes = []
    user.CloseClipboard.restype = wintypes.BOOL
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalSize.restype = ctypes.c_size_t
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalUnlock.restype = wintypes.BOOL
    format_id = user.RegisterClipboardFormatW("HTML Format")
    if not format_id or not user.OpenClipboard(None):
        return b""
    try:
        handle = user.GetClipboardData(format_id)
        size = kernel.GlobalSize(handle) if handle else 0
        if not 0 < size <= 16 * 1024 * 1024:
            return b""
        pointer = kernel.GlobalLock(handle)
        if not pointer:
            return b""
        try:
            return ctypes.string_at(pointer, size)
        finally:
            kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


def paste_content(text, html=b""):
    """Prefer the hyperlink destination over its displayed title."""
    links = clipboard_html_links(html) if html else []
    if not links:
        links = html_links(text)
    return "\n".join(links) if links else text
