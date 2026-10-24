"""URL classification and discovery, independent of the browser and GUI."""

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, unquote, urldefrag, urljoin, urlsplit, urlunsplit

FILECRYPT_HOSTS = {"filecrypt.cc", "filecrypt.co", "filecrypt.to"}
PASTE_HOSTS = {"paste.fitgirl-repacks.site", "pastebin.com", "rentry.co", "rentry.org"}
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`\\]+", re.I)
OPEN_LINK = re.compile(r"\bopenLink\w*\s*\(\s*['\"]([^'\"]+)['\"]", re.I)
DOWNLOAD_CALL = re.compile(r"^[\w$]+\s*\(\s*['\"]([A-Za-z0-9_-]+)['\"]")


def normalize_url(value: str, base: str = "") -> str:
    value = unescape(value.strip()).replace(r"\/", "/")
    if base:
        value = urljoin(base, value)
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("http:// 또는 https:// URL을 입력하세요.")
        if parts.username is not None or parts.password is not None:
            raise ValueError("인증 정보가 포함된 URL은 지원하지 않습니다.")
        port = parts.port  # Validate before building a canonical URL.
        host = parts.hostname.encode("idna").decode("ascii").lower()
        if ":" in host:
            host = f"[{host}]"
        if port and not ((parts.scheme.lower() == "https" and port == 443) or
                         (parts.scheme.lower() == "http" and port == 80)):
            host += f":{port}"
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, parts.fragment))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"올바르지 않은 URL: {value}") from exc


def url_key(url: str) -> str:
    return urldefrag(normalize_url(url))[0]


def kind_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if re.fullmatch(r"dl\d*\.fuckingfast\.co", host):
        return "direct"
    if host in {"fuckingfast.co", "www.fuckingfast.co"}:
        return "ff"
    if host.removeprefix("www.") in FILECRYPT_HOSTS:
        path = urlsplit(url).path.lower()
        if path.startswith("/link/"):
            return "filecrypt-link"
        if path.startswith("/container/"):
            return "filecrypt"
    if host in PASTE_HOSTS:
        return "paste"
    return "page"


def display_name(url: str) -> str:
    parts = urlsplit(url)
    return unquote(parts.fragment or parts.path.rstrip("/").rsplit("/", 1)[-1] or parts.hostname or url)


def parse_input(text: str) -> list[str]:
    """One URL per line; reject invalid lines instead of silently losing input."""
    result = {}
    for line in text.splitlines():
        if line.strip():
            url = normalize_url(line)
            if any(c.isspace() for c in url):
                raise ValueError("URL은 한 줄에 하나씩 입력하세요. 공백은 %20으로 표시하세요.")
            result.setdefault(url_key(url), url)
    if not result:
        raise ValueError("추출할 URL을 한 개 이상 입력하세요.")
    return list(result.values())


@dataclass(frozen=True)
class Candidate:
    url: str
    name: str = ""
    expected_host: str = ""


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.texts = []
        self.stack = []
        self.row_name = ""
        self.row_host = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row_name = ""
            self.row_host = ""
        style = re.sub(r"\s+", "", attrs.get("style") or "").lower()
        hidden = (any(item[1] for item in self.stack) or "hidden" in attrs or
                  attrs.get("aria-hidden") == "true" or "display:none" in style or
                  "visibility:hidden" in style)
        if not hidden:
            if tag == "td" and attrs.get("title"):
                self.row_name = attrs["title"]
            if tag == "a" and "external_link" in (attrs.get("class") or "").split():
                self.row_host = urlsplit(attrs.get("href") or "").hostname or ""
            if self.row_name:
                attrs = {**attrs, "_row_name": self.row_name, "_row_host": self.row_host}
            self.elements.append((tag, attrs))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        if tag == "tr":
            self.row_name = ""
            self.row_host = ""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(item[1] for item in self.stack):
            self.texts.append(data)


def discover(html: str, base: str) -> list[Candidate]:
    """Find supported links, Filecrypt mirrors and openLink row controls.

    Unknown links are deliberately not crawled: a content page can contain an
    entire site navigation menu and ads unrelated to its download links.
    """
    parser = _Parser()
    parser.feed(html)
    found: dict[str, Candidate] = {}
    base_kind = kind_of(base)

    def add(value, name="", expected_host=""):
        if not value:
            return
        try:
            url = normalize_url(value, base)
        except ValueError:
            return
        kind = kind_of(url)
        if kind == "page":
            # Common outbound wrappers carry their destination in a query value.
            for _, destination in parse_qsl(urlsplit(url).query):
                try:
                    target = normalize_url(destination)
                except ValueError:
                    continue
                if kind_of(target) != "page":
                    add(target, name, expected_host)
            return
        if kind == "ff" and urlsplit(url).path in {"", "/"}:
            return
        if kind == "ff" and urlsplit(url).path.rstrip("/").lower() in {
            "/help", "/terms", "/privacy", "/contact", "/login", "/register", "/speedtest",
        }:
            return
        if kind == "filecrypt" and "mirror=666" in urlsplit(url).query:
            return
        if url_key(url) != url_key(base):
            found.setdefault(url_key(url), Candidate(url, name or display_name(url), expected_host))

    for tag, attrs in parser.elements:
        if tag in {"a", "area"}:
            add(attrs.get("href"), attrs.get("_row_name") or attrs.get("title", ""), attrs.get("_row_host", ""))
        if base_kind.startswith("filecrypt"):
            onclick = attrs.get("onclick") or ""
            match = OPEN_LINK.search(onclick)
            if not match and "download" in (attrs.get("class") or "").split():
                match = DOWNLOAD_CALL.search(onclick)
            if match:
                target = match.group(1)
                if not target.startswith(("http://", "https://", "/")):
                    target = f"/Link/{target}.html"
                add(target, attrs.get("_row_name") or attrs.get("title", ""), attrs.get("_row_host", ""))
        for match in URL_PATTERN.finditer(attrs.get("onclick") or ""):
            add(match.group(0))

    # Includes raw paste text, JSON-escaped URLs, inline window.open and redirects.
    decoded = unescape("\n".join(parser.texts)).replace(r"\/", "/")
    for match in URL_PATTERN.finditer(decoded):
        add(match.group(0))
    return list(found.values())
