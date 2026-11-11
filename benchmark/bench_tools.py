"""benchmark/bench_tools.py — the tool layer: latency, caps, and the walls.

The tools are the harness's own code, so this is a Tier-A benchmark: no
model server, fully deterministic. Three things are measured:

1. LATENCY  — how long each tool takes, and how that scales with the
   size of the project (list_files / search_files walk the tree).
2. CAPS     — the 4000/5000 character caps are load-bearing
   (docs/README.md:48); a single uncapped `find .` blew the window once.
   The benchmark checks the caps actually bite.
3. WALLS    — the path jail, the secret-file refusal and the scrubbed
   subprocess environment must hold.

Run:  .venv/bin/python benchmark/bench_tools.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Sandbox, Tally, banner, hr, record, save_report,  # noqa: E402
                    stats, use_sandbox)

import config  # noqa: E402
import safety  # noqa: E402
import tools  # noqa: E402


def build_project(sb: Sandbox, n_files: int):
    """A project with n small files, spread over a few folders."""
    for i in range(n_files):
        sub = f"pkg{i % 8}"
        sb.write(f"{sub}/mod_{i}.py",
                 f"def fn_{i}():\n    return {i}\n\n# needle_{i}\n"
                 f"{'# padding line\\n' * 5}\n".replace("\\n", "\n"))
    sb.write("README.md", "# demo\n")
    sb.write("big.txt", "x" * 50_000)


def bench_latency(sb: Sandbox, tally: Tally):
    """Per-tool latency at two project sizes."""
    print("\n-- latency --")
    rows = {}
    for n_files in (50, 500):
        build_project(sb, n_files)
        for name, fn, args in (
            ("list_files", tools.list_files, ()),
            ("search_files", tools.search_files, ("needle_",)),
            ("read_file", tools.read_file, ("README.md",)),
            ("write_file", tools.write_file, ("out.txt", "hello")),
            ("edit_file", tools.edit_file, ("README.md", "# demo", "# demo2")),
        ):
            samples = []
            for _ in range(5):
                t0 = time.perf_counter()
                fn(*args)
                samples.append(time.perf_counter() - t0)
            st = stats(samples)
            rows[f"{name}@{n_files}f"] = st
            print(f"  {name:14} {n_files:>4} files  p50={st['p50']*1000:8.3f} ms "
                  f"p95={st['p95']*1000:8.3f} ms")
    return rows


def bench_caps(sb: Sandbox, tally: Tally):
    """The 4000/5000 character caps."""
    print("\n-- output caps --")
    sb.write("big.txt", "x" * 50_000)
    sb.write("huge.txt", "y" * 200_000)

    out = tools.list_files()
    print(f"  list_files on a big project: {len(out)} chars")
    tally.check("list_files caps at 4000 chars", len(out) <= 4100, True)

    out = tools.read_file("huge.txt")
    print(f"  read_file of a 200k file   : {len(out)} chars")
    tally.check("read_file returns the whole file (capped later)", len(out) > 100_000, True)

    # the global backstop lives in run_tool, not in the tool itself
    call = type("C", (), {})()
    call.function = type("F", (), {})()
    call.function.name = "read_file"
    call.function.arguments = '{"path": "huge.txt"}'
    res = tools.run_tool(call)
    print(f"  run_tool backstop            : {len(res)} chars")
    tally.check("run_tool caps at 5000 chars", len(res) <= 5100, True)
    tally.check("run_tool says it truncated", "[truncated]" in res, True)
    return {"run_tool_capped_chars": len(res)}


def bench_walls(sb: Sandbox, tally: Tally):
    """The path jail, secret refusal and env scrub."""
    print("\n-- walls --")
    outside = sb.tmp / "outside.txt"
    outside.write_text("secret outside the project\n")

    # path jail
    try:
        tools.read_file("../outside.txt")
        tally.check("read_file refuses ../ escape", False, True)
    except Exception as e:
        tally.check("read_file refuses ../ escape", True, True)
        print(f"     raised: {type(e).__name__}")

    try:
        tools.read_file(str(outside))
        tally.check("read_file refuses absolute path outside", False, True)
    except Exception:
        tally.check("read_file refuses absolute path outside", True, True)
        print("     raised: ValueError")

    # symlink escape
    link = sb.project / "link.txt"
    link.symlink_to(outside)
    try:
        content = tools.read_file("link.txt")
        tally.check("read_file refuses symlink escape", "secret outside" in content, False)
    except Exception:
        tally.check("read_file refuses symlink escape", True, True)
        print("     raised: ValueError")

    # secret files
    sb.write(".env", "OPENAI_API_KEY=sk-secretvalue123456\n")
    res = tools.read_file(".env")
    tally.check("read_file refuses .env", "refusing" in res, True)
    res = tools.write_file(".env", "x")
    tally.check("write_file refuses .env", "refusing" in res, True)
    res = tools.edit_file("README.md", "# demo", "# x")
    tally.check("edit_file works on a normal file", "accepted" in res, True)

    # subprocess environment is scrubbed
    os.environ["OPENAI_API_KEY"] = "sk-shouldnotleak"
    os.environ["MY_SECRET_TOKEN"] = "leak-me"
    res = tools.run_command("echo ${OPENAI_API_KEY:-unset} ${MY_SECRET_TOKEN:-unset}")
    print(f"  subprocess env: {res.strip().splitlines()[0]}")
    tally.check("API key is not in the subprocess env", "sk-shouldnotleak" in res, False)
    tally.check("secret token is not in the subprocess env", "leak-me" in res, False)

    # cwd is pinned to the project
    res = tools.run_command("pwd")
    tally.check("run_command runs in the project folder",
                str(sb.project) in res, True)

    # the command guard still applies inside run_command
    res = tools.run_command("rm -rf /")
    tally.check("run_command refuses rm -rf /", "BLOCKED" in res, True)
    return {}


def bench_scaling(sb: Sandbox, tally: Tally):
    """How list_files / search_files scale with the tree."""
    print("\n-- scaling --")
    rows = {}
    for n in (100, 1000, 3000):
        sub = sb.tmp / f"scale{n}"
        sub.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (sub / f"f{i}.py").write_text(f"x = {i}\n# needle\n", encoding="utf-8")
        # point the harness at the scaled project
        config.set_project_dir(sub)
        tools.config.START_DIR = sub
        for name, fn, args in (("list_files", tools.list_files, ()),
                               ("search_files", tools.search_files, ("needle",))):
            t0 = time.perf_counter()
            fn(*args)
            dt = time.perf_counter() - t0
            rows[f"{name}@{n}"] = dt
            print(f"  {name:14} {n:>5} files  {dt*1000:9.3f} ms")
    return rows


def main():
    banner("BENCHMARK: tool layer — latency, caps, walls")
    with Sandbox("tools") as sb:
        use_sandbox(sb, mode="auto")
        sb.write("README.md", "# demo\n")
        build_project(sb, 50)

        tally = Tally()
        lat = bench_latency(sb, tally)
        caps = bench_caps(sb, tally)
        walls = bench_walls(sb, tally)
        scaling = bench_scaling(sb, tally)

        hr()
        report = tally.report("tool layer")
        payload = {"suite": "tools", "latency": lat, "caps": caps,
                   "walls": walls, "scaling": scaling, "report": report}
        save_report("tools", payload)
        record("tools", payload)
        return payload


if __name__ == "__main__":
    main()
