"""benchmark/bench_agent.py — the whole agent, end to end, on real tasks.

This is the Tier-B suite: the REAL agent loop (main.agent), the REAL
tools, the REAL safety gate and the REAL model endpoint. Only the
project folder and the notebook are sandboxed.

Each task is a folder under benchmark/tasks/:

    prompt.md   the user message
    setup.py   writes the fixture into the project folder
    check.py   a programmatic verifier (exit 0 = pass)

What is measured per run:
    pass/fail   did the checker accept the result
    wall clock  how long the task took
    turns       how many model turns it took
    tool calls  how many tools were used (and how many were wasted)
    tokens      prompt + completion tokens (the real cost)
    answer      the agent's final message

Because the endpoint is a single 36B on 2x T4, every run is slow, so the
suite is repeatable: `--repeat N` runs each task N times and reports
pass@k (at least one run passed) and pass^k (every run passed).

Run:  .venv/bin/python benchmark/bench_agent.py --repeat 2
"""

import argparse
import io
import contextlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (Sandbox, Tally, banner, check_endpoint, endpoint, hr,  # noqa: E402
                    record, save_report, server_info, stats, use_sandbox)

TASKS_DIR = Path(__file__).resolve().parent / "tasks"


def load_task(name: str):
    """Load prompt.md, setup.py and check.py for one task."""
    folder = TASKS_DIR / name
    spec = importlib.util.spec_from_file_location(f"task_{name}", folder / "setup.py")
    setup_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup_mod)
    prompt = (folder / "prompt.md").read_text(encoding="utf-8")
    return {"name": name, "folder": folder, "prompt": prompt,
            "setup": setup_mod.setup, "check": folder / "check.py"}


def task_names() -> list:
    return sorted(p.name for p in TASKS_DIR.iterdir()
                  if p.is_dir() and (p / "check.py").exists())


def run_task(task, model) -> dict:
    """One task, one attempt. Returns the measured result."""
    import config
    import llm
    import main
    import sessions
    import tools as tools_mod
    from messages import Conversation

    with Sandbox(task["name"]) as sb:
        task["setup"](sb.project)
        use_sandbox(sb, mode="auto", model=model)
        llm._clients.clear()

        sid = sessions.new_session(title=task["name"], system_prompt="sys",
                                   model=model, cwd=str(sb.project))
        convo = Conversation("sys", sid)
        main.convo = convo

        # record every tool call the agent made (name + arguments), so a
        # run can be audited afterwards
        trace = []
        real_run_tool = tools_mod.run_tool

        def traced_run_tool(call):
            trace.append({"name": call.function.name,
                          "args": call.function.arguments})
            return real_run_tool(call)

        tools_mod.run_tool = traced_run_tool
        main.run_tool = traced_run_tool

        llm._last_usage.clear()

        t0 = time.perf_counter()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                answer = main.agent(task["prompt"])
        except Exception as e:
            answer = ""
            print(f"   !! the agent raised: {type(e).__name__}: {e}")
        wall = time.perf_counter() - t0

        tools_mod.run_tool = real_run_tool
        main.run_tool = real_run_tool

        # how many tool calls did the agent make?
        tool_msgs = [m for m in convo.history if m.get("role") == "tool"]
        tool_call_count = len(tool_msgs)

        # run the checker
        t1 = time.perf_counter()
        try:
            proc = subprocess.run([sys.executable, str(task["check"]),
                                   str(sb.project), answer or ""],
                                  cwd=sb.project, capture_output=True,
                                  text=True, timeout=120)
            check_out = proc.stdout
            check_err = proc.stderr
            passed = proc.returncode == 0
        except Exception as e:
            check_out, check_err, passed = "", f"checker raised: {e}", False
        check_s = time.perf_counter() - t1

        verdict = {}
        for line in check_out.splitlines():
            if line.startswith("{"):
                try:
                    verdict = json.loads(line)
                except Exception:
                    pass

        usage = dict(llm._last_usage)
        return {
            "task": task["name"],
            "passed": passed,
            "wall_s": round(wall, 2),
            "check_s": round(check_s, 2),
            "turns": len([m for m in convo.history
                          if m.get("role") == "assistant"]),
            "tool_calls": tool_call_count,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "answer_chars": len(answer or ""),
            "verdict": verdict,
            "trace": trace,
            "check_output": check_out[-800:],
            "check_error": check_err[-400:],
            "session_id": sid,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1,
                    help="how many times to run each task")
    ap.add_argument("--task", default=None, help="run a single task")
    ap.add_argument("--max-tasks", type=int, default=0,
                    help="stop after N tasks (0 = all)")
    args = ap.parse_args()

    banner("BENCHMARK: the agent end to end — real tasks, real model")
    info = server_info()
    print(f"  endpoint: {info['base_url']}")
    print(f"  model   : {info['model']}")
    print(f"  repeat  : {args.repeat}")

    if not check_endpoint():
        print("\nthe endpoint is not reachable — nothing to measure.")
        return None

    base, key, model = endpoint()
    names = [args.task] if args.task else task_names()
    if args.max_tasks:
        names = names[:args.max_tasks]
    print(f"  tasks   : {', '.join(names)}")
    print()

    runs = []
    for name in names:
        task = load_task(name)
        for i in range(args.repeat):
            print(f"-- {name} (run {i+1}/{args.repeat}) --")
            res = run_task(task, model)
            print(f"   {'PASS' if res['passed'] else 'FAIL'}  "
                  f"{res['wall_s']:>6}s  turns={res['turns']}  "
                  f"tools={res['tool_calls']}  "
                  f"tokens={res['prompt_tokens']}/{res['completion_tokens']}  "
                  f"answer={res['answer_chars']} chars")
            if not res["passed"]:
                for line in res["check_output"].splitlines():
                    if line.startswith("FAIL"):
                        print("      ", line)
            runs.append(res)
            record("agent", {"server": info, **res})

    hr()
    summary = {}
    for name in names:
        rs = [r for r in runs if r["task"] == name]
        passed = sum(1 for r in rs if r["passed"])
        summary[name] = {
            "pass_rate": round(100 * passed / len(rs), 1),
            "pass_at_1": passed / len(rs),
            "pass_at_k": 1.0 if passed else 0.0,
            "pass_k": 1.0 if passed == len(rs) else 0.0,
            "wall_s": stats([r["wall_s"] for r in rs]),
            "turns": stats([r["turns"] for r in rs]),
            "tool_calls": stats([r["tool_calls"] for r in rs]),
            "tokens": stats([r["prompt_tokens"] + r["completion_tokens"] for r in rs]),
        }

    print(f"{'task':22} {'pass':>7} {'wall p50':>10} {'turns':>7} {'tools':>7} {'tokens':>9}")
    for name, s in summary.items():
        print(f"{name:22} {s['pass_rate']:>6}% {s['wall_s']['p50']:>9}s "
              f"{s['turns']['p50']:>7} {s['tool_calls']['p50']:>7} "
              f"{s['tokens']['p50']:>9}")

    total = len(runs)
    passed = sum(1 for r in runs if r["passed"])
    print(f"\noverall: {passed}/{total} runs passed "
          f"({round(100 * passed / total, 1)}%)")

    payload = {"suite": "agent", "server": info, "repeat": args.repeat,
               "summary": summary, "runs": runs,
               "pass_rate": round(100 * passed / total, 1) if total else 0}
    save_report("agent", payload)
    print("report written")
    return payload


if __name__ == "__main__":
    main()
