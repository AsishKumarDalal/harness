"""web.py — the two internet tools: search and fetch.

  web_search(query)  -> DuckDuckGo results (via the `ddgs` package)
  web_fetch(url)     -> a page as text: HTML is stripped, GitHub blob URLs
                        are rewritten to raw.githubusercontent.com

Both only read — they never touch the project folder.

web_fetch refuses URLs that point back at the machine (localhost, private
ranges, the cloud metadata address) so a prompt in the page cannot use the
agent to read local services. The host is also checked after DNS, and every
redirect is checked too.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "harness-agent/1.0 (+https://github.com/AsishKumarDalal/harness)"
MAX_BYTES = 2_000_000        # never download more than 2 MB
TIMEOUT = 20                 # seconds
MAX_CHARS = 4000             # characters handed back to the model

BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "instance-data",
}

# github.com/<owner>/<repo>/blob/<ref>/<path>  ->  raw.githubusercontent.com/...
_GITHUB_BLOB = re.compile(
    r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/blob/(.+)$", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """Is this address safe to fetch (not loopback/private/link-local/...)?"""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _check_url(url: str) -> str:
    """Validate a URL; raises ValueError when it may not be fetched."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        scheme = parsed.scheme or "none"
        raise ValueError(f"only http(s) URLs are allowed (got '{scheme}')")
    host = (parsed.hostname or "").lower().strip("[]")
    if not host:
        raise ValueError("the URL has no host")
    if host in BLOCKED_HOSTS or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError(f"refusing to fetch a local address ({host})")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not _is_public_ip(ip):
        raise ValueError(f"refusing to fetch a private address ({ip})")
    return url


def _resolves_public(host: str) -> bool:
    """Best effort: does the name point at a public address?"""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True                      # cannot resolve: let the request fail
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not _is_public_ip(ip):
            return False
    return True


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    """Check every redirect target too — a public URL may redirect inward."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------------------
# html -> text
# ---------------------------------------------------------------------------

class _TextExtractor(HTMLParser):
    """Collect the readable text of an HTML page."""

    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table",
        "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
        "footer", "pre", "blockquote", "hr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _html_to_text(source: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        return source
    return parser.text()


def _clean(text: str) -> str:
    """Tidy the text: unescape entities, squeeze spaces, cap blank lines."""
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _rewrite(url: str) -> str:
    """A GitHub blob URL becomes the raw file URL."""
    match = _GITHUB_BLOB.match(url)
    if match:
        owner, repo, rest = match.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{rest}"
    return url


# ---------------------------------------------------------------------------
# the two tools
# ---------------------------------------------------------------------------

def search(query: str, max_results: int = 5) -> str:
    """Search the web with DuckDuckGo (no API key needed)."""
    query = (query or "").strip()
    if not query:
        return "error: query is empty"
    try:
        from ddgs import DDGS
    except ImportError:
        return ("error: the 'ddgs' package is missing — "
                "install it with: pip install ddgs")
    try:
        results = DDGS().text(query, max_results=max(int(max_results), 1))
    except Exception as exc:
        return f"error: search failed ({type(exc).__name__}: {exc})"
    if not results:
        return f"no results for '{query}'"
    lines = []
    for number, item in enumerate(results, 1):
        title = str(item.get("title") or "").strip()
        href = str(item.get("href") or "").strip()
        body = str(item.get("body") or "").strip()
        lines.append(f"{number}. {title}\n   {href}\n   {body}")
    return "\n".join(lines)


def fetch(url: str, max_chars: int = MAX_CHARS) -> str:
    """Fetch a URL and return it as plain text."""
    url = (url or "").strip()
    if not url:
        return "error: url is empty"
    if "://" not in url:
        url = "https://" + url
    url = _rewrite(url)

    try:
        _check_url(url)
    except ValueError as exc:
        return f"error: {exc}"

    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host and not _resolves_public(host):
        return f"error: refusing to fetch a private address ({host})"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    opener = urllib.request.build_opener(_RedirectGuard())
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            raw = response.read(MAX_BYTES)
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        return f"error: HTTP {exc.code} for {url}"
    except urllib.error.URLError as exc:
        return f"error: cannot reach {url} ({exc.reason})"
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"

    text = raw.decode("utf-8", errors="replace")
    head = text.lstrip()[:200].lower()
    if "html" in content_type.lower() or head.startswith(("<!doctype html", "<html")):
        text = _html_to_text(text)
    text = _clean(text)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    if not text:
        return f"[{final_url}]\n(empty response)"
    return f"[{final_url}]\n\n{text}"
