"""benchmark/test_tasks.py — are the task checkers themselves correct?

A benchmark is only as good as its verifier. A checker that always
passes would report a 100% success rate for a broken agent; a checker
that can never pass would report 0% for a perfect one.

So every checker must satisfy BOTH properties:

    strict        the unsolved fixture FAILS the check
    satisfiable   a reference solution PASSES the check

This script proves both, offline, in a second. Run it whenever a task
or its checker changes.

Run:  .venv/bin/python benchmark/test_tasks.py
"""

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

# A reference solution for every task. If the checker cannot be
# satisfied by this, the checker is wrong.
SOLUTIONS = {
    "fix_off_by_one": {
        "calc.py": 'def sum_range(start, end):\n    return sum(range(start, end + 1))\n',
    },
    "add_cli_flag": {
        "greet.py": '''import sys


def greet(name):
    return f"Hello, {name}!"


def main(argv):
    verbose = "--verbose" in argv
    argv = [a for a in argv if a != "--verbose"]
    name = argv[0] if argv else "world"
    print(greet(name))
    if verbose:
        print("Greeting completed.")


if __name__ == "__main__":
    main(sys.argv[1:])
''',
    },
    "rename_across_files": {
        "a.py": 'def compute_total(prices):\n    return sum(prices)\n',
        "b.py": 'from a import compute_total\n\nPRICES = [10, 20, 30]\n\n\ndef basket_total():\n    return compute_total(PRICES)\n',
        "c.py": 'from a import compute_total\n\nITEMS = [1.5, 2.5]\n\n\ndef items_total():\n    return compute_total(ITEMS)\n',
    },
    "write_tests": {
        "test_mathlib.py": '''from mathlib import is_prime


def main():
    assert is_prime(2) and is_prime(3) and is_prime(5)
    assert is_prime(7) and is_prime(11)
    assert not is_prime(0) and not is_prime(1) and not is_prime(-3)
    assert not is_prime(4) and not is_prime(9) and not is_prime(25)
    print("all good")


if __name__ == "__main__":
    main()
''',
    },
}

ANSWERS = {
    "explain_code": ("The transform function uppercases the name field of every "
                     "row and returns the list of uppercase names."),
}

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(("ok  " if ok else "FAIL"), label, detail)
    passed += ok
    failed += not ok


def load_setup(task):
    spec = importlib.util.spec_from_file_location(
        f"setup_{task}", TASKS_DIR / task / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.setup


def run_checker(task, project, answer=""):
    return subprocess.run(
        [sys.executable, str(TASKS_DIR / task / "check.py"), str(project), answer],
        cwd=project, capture_output=True, text=True, timeout=120)


def main():
    print("=" * 68)
    print(" task checkers: strict AND satisfiable")
    print("=" * 68)
    tasks = sorted(p.name for p in TASKS_DIR.iterdir()
                   if p.is_dir() and (p / "check.py").exists())
    for task in tasks:
        setup = load_setup(task)

        # 1. the unsolved fixture must FAIL
        d = Path(tempfile.mkdtemp())
        setup(d)
        r = run_checker(task, d, "")
        fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
        check(f"{task}: strict (the unsolved fixture fails)",
              r.returncode != 0 and bool(fails),
              f"rc={r.returncode}, {len(fails)} failing checks")

        # 2. the reference solution must PASS
        d2 = Path(tempfile.mkdtemp())
        setup(d2)
        for name, content in SOLUTIONS.get(task, {}).items():
            (d2 / name).write_text(content, encoding="utf-8")
        r2 = run_checker(task, d2, ANSWERS.get(task, ""))
        check(f"{task}: satisfiable (the reference solution passes)",
              r2.returncode == 0,
              f"rc={r2.returncode} {r2.stdout.strip()[-200:]}")

    print(f"\n{passed}/{passed + failed} checks ok")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
