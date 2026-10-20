"""Probe for the web tools: the guards, the URL rewriting, the HTML stripping.

Run:  .venv/bin/python test/test_web.py   (from project root)

The offline checks always run. The two live checks (a real search and a real
fetch) only run when the network is there; they are reported as warnings, not
failures, so this test stays useful offline.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools  # noqa: E402
import web  # noqa: E402

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


def warn(label, detail=""):
    print("warn", label, detail)


# --- the tools are registered ------------------------------------------------
check("web_search is a tool", "web_search" in tools.REGISTRY)
check("web_fetch is a tool", "web_fetch" in tools.REGISTRY)
check(
    "both are in the model schema",
    {t["function"]["name"] for t in tools.SCHEMA} >= {"web_search", "web_fetch"},
)

# --- the safety tiers --------------------------------------------------------
import safety  # noqa: E402

check("web_search is free (a read)", "web_search" in safety.FREE_TOOLS)
check("web_fetch asks first (like curl)", "web_fetch" in safety.ASK_TOOLS)

_mode = safety.MODE                     # do not touch the saved settings file
try:
    safety.MODE = "plan"
    check("web_fetch is blocked in plan mode",
          "plan mode" in (safety.blocked_tool_message("web_fetch", {"url": "https://x.com"}) or ""))
    check("web_search is allowed in plan mode",
          safety.blocked_tool_message("web_search", {"query": "x"}) is None)
finally:
    safety.MODE = _mode

# --- local addresses are refused ---------------------------------------------
for url in [
    "http://127.0.0.1:8080/secret",
    "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
    "http://10.0.0.5/internal",
    "http://192.168.1.1/router",
    "http://[::1]/x",
    "http://foo.localhost/x",
]:
    result = tools.web_fetch(url)
    check(f"refuses {url}", result.startswith("error:"), f"-> {result[:52]}")

# --- github blob urls become raw urls ----------------------------------------
check(
    "github blob url -> raw url",
    web._rewrite("https://github.com/owner/repo/blob/main/src/app.py")
    == "https://raw.githubusercontent.com/owner/repo/main/src/app.py",
)
check(
    "other urls are left alone",
    web._rewrite("https://example.com/a/b") == "https://example.com/a/b",
)

# --- html becomes text --------------------------------------------------------
html_source = """
<html><head><title>t</title><style>body{color:red}</style></head>
<body><script>var x = 1;</script><h1>Hello</h1><p>One &amp; two</p>
<ul><li>first</li><li>second</li></ul></body></html>
"""
text = web._html_to_text(html_source)
check("html title text kept", "Hello" in text)
check("html entities unescaped", "One & two" in text)
check("script content dropped", "var x" not in text)
check("style content dropped", "color:red" not in text)

# --- empty input --------------------------------------------------------------
check("empty search", tools.web_search("").startswith("error:"))
check("empty fetch", tools.web_fetch("").startswith("error:"))

# --- live checks (network) ----------------------------------------------------
try:
    results = tools.web_search("python textual terminal ui", max_results=2)
    if results.startswith("error:"):
        warn("live search", results[:60])
    else:
        check("live search returns results", "1." in results)
        check("live search has urls", "http" in results)
except Exception as exc:  # pragma: no cover
    warn("live search", str(exc)[:60])

try:
    page = tools.web_fetch("https://raw.githubusercontent.com/Textualize/textual/main/README.md")
    if page.startswith("error:"):
        warn("live fetch", page[:60])
    else:
        check("live fetch returns the file", "textual" in page.lower())
except Exception as exc:  # pragma: no cover
    warn("live fetch", str(exc)[:60])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
