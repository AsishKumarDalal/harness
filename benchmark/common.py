"""benchmark/common.py — shared helpers for every benchmark suite.

Two things live here:

1. **Isolation.** A benchmark must never touch the developer's real state.
   `Sandbox` gives every run a throwaway project folder AND a throwaway
   $HARNESS_HOME (notebook, safety rules, settings), so runs never bleed
   into each other or into ~/.harness.

2. **Measurement.** `check()` (the repo's assert style, same as test/),
   `stats()` (percentiles) and `record()` (append a JSONL row so results
   can be compared across runs and across commits).

The endpoint can be overridden with BENCH_BASE_URL / BENCH_API_KEY /
BENCH_MODEL; otherwise the .env settings are used.
"""

import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True      # keep __pycache__ out of the project

import config  # noqa: E402

RESULTS_DIR = BENCH_DIR / "results"

# The endpoint this suite was written against. Overridable by env vars so a
# different box (or a local ollama) can be benchmarked without editing code.
DEFAULT_BASE_URL = "https://small-present-educated-believe.trycloudflare.com/v1"
DEFAULT_API_KEY = "ollama"
DEFAULT_MODEL = "k2-horizon-mova-36b-a4b"


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------

def endpoint() -> tuple[str, str, str]:
    """(base_url, api_key, model) for the live suites.

    The .env values win over the machine-wide settings: a machine that
    once saved an endpoint with `/model add` would otherwise send the
    benchmark to a stale (dead) tunnel, because llm.endpoint_for()
    prefers a saved provider for the model name.
    """
    base = (os.getenv("BENCH_BASE_URL") or os.getenv("BASE_URL")
            or config.BASE_URL or DEFAULT_BASE_URL)
    key = (os.getenv("BENCH_API_KEY") or os.getenv("OPENAI_API_KEY")
           or config.API_KEY or DEFAULT_API_KEY)
    model = (os.getenv("BENCH_MODEL") or os.getenv("MODEL")
             or config.MODEL or DEFAULT_MODEL)
    return base, key, model


def server_info() -> dict:
    """What we are talking to — recorded with every result."""
    base, key, model = endpoint()
    return {
        "base_url": base,
        "model": model,
        "host": base.split("/")[2] if "//" in base else base,
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
    }


def check_endpoint() -> bool:
    """Is the endpoint reachable? Prints a friendly reason if not."""
    import socket
    from urllib.parse import urlparse

    base, key, model = endpoint()
    host = urlparse(base).hostname
    if not host:
        print("no base url configured")
        return False
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror as e:
        print(f"!! the endpoint host '{host}' does not resolve ({e}).")
        print("   The trycloudflare tunnel changes when the box restarts —")
        print("   update BASE_URL in .env (or set BENCH_BASE_URL).")
        return False
    print(f"endpoint reachable: {host}")
    return True


# ---------------------------------------------------------------------------
# isolation
# ---------------------------------------------------------------------------

class Sandbox:
    """A throwaway project folder + HARNESS_HOME."""

    def __init__(self, name="bench"):
        self.tmp = Path(tempfile.mkdtemp(prefix=f"hbench-{name}-"))
        self.project = self.tmp / "project"
        self.home = self.tmp / "home"
        self.project.mkdir(parents=True)
        self.home.mkdir(parents=True)

    def write(self, rel: str, content: str) -> Path:
        p = self.project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()
        return False


def use_sandbox(sb: Sandbox, mode: str = "auto", model: str | None = None):
    """Point the whole harness at the sandbox. Returns the sandbox.

    Notes:
      * safety.MODE='auto' is REQUIRED for unattended runs: gate_one()
        refuses to prompt when stdin is not a tty (safety.py:461), so in
        'ask' mode every write/run_command would be silently denied and
        the benchmark would measure nothing.
      * hardline commands are still refused in auto mode — command_guard()
        runs before the auto shortcut (safety.py:450).
      * sessions.DB_PATH is a module constant set at import time, so it
        has to be repointed by hand.
    """
    import llm
    import safety
    import sessions
    import tools

    config.set_project_dir(sb.project)
    config.HARNESS_HOME = sb.home
    sessions.DB_PATH = sb.home / "state.db"
    safety.SETTINGS_PATH = sb.home / "safety.json"
    safety.MODE = mode
    safety.RULES = []
    tools.set_quiet(True)
    llm._clients.clear()

    # The machine-wide settings can point a model at a saved endpoint
    # (`/model add`). Those may be stale — a trycloudflare tunnel from
    # last week — and llm.endpoint_for() would prefer them over
    # BASE_URL. Ignore them for the benchmark, and make sure a stray
    # save_settings() cannot touch the real file.
    config.SETTINGS_PATH = sb.home / "settings.json"
    config.SETTINGS.pop("model_provider", None)
    config.SETTINGS.pop("providers", None)

    if model:
        config.MODEL = model
    return sb


def reset_state():
    """Drop the notebook between runs (keeps the same sandbox)."""
    import sessions
    sessions._local.__dict__.clear()


# ---------------------------------------------------------------------------
# assertions (same style as test/)
# ---------------------------------------------------------------------------

class Tally:
    """ok/fail counter shared by the suites."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def check(self, label, got, want=True):
        ok = got == want
        print(("ok  " if ok else "FAIL"), label, "->", repr(got))
        self.passed += ok
        self.failed += not ok
        if not ok:
            self.failures.append(f"{label} -> got {got!r}, want {want!r}")
        return ok

    def report(self, title: str) -> dict:
        total = self.passed + self.failed
        rate = round(100 * self.passed / total, 1) if total else 0.0
        print(f"\n{title}: {self.passed}/{total} ok ({rate}%)")
        for f in self.failures:
            print("   FAILED:", f)
        return {"title": title, "passed": self.passed, "failed": self.failed,
                "total": total, "pass_rate": rate, "failures": self.failures}


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

def stats(values) -> dict:
    """min/p50/p95/max/mean over a list of numbers.

    Rounded to 6 decimals (microseconds) — the harness does a lot of
    sub-millisecond work (a SQLite insert is ~50 us) and a coarser
    rounding would report it as zero.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    p95 = s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]
    return {
        "n": len(s),
        "min": round(s[0], 6),
        "p50": round(statistics.median(s), 6),
        "p95": round(p95, 6),
        "max": round(s[-1], 6),
        "mean": round(statistics.mean(s), 6),
        "total": round(sum(s), 6),
    }


def timed(fn, *args, **kwargs):
    """Run fn, return (result, seconds)."""
    t0 = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

def record(name: str, payload: dict) -> Path:
    """Append one JSONL row to results/<name>.jsonl."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.jsonl"
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return path


def save_report(name: str, payload: dict) -> Path:
    """Write a full JSON report to results/<name>.json."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def banner(title: str) -> None:
    print("=" * 68)
    print(" " + title)
    print("=" * 68)


def hr(char="-"):
    print(char * 68)
