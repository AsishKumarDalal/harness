"""Check the add_cli_flag task: `python greet.py --verbose Alice` must print two lines."""

import json
import subprocess
import sys


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    checks = []

    try:
        r = subprocess.run([sys.executable, "greet.py", "--verbose", "Alice"],
                           cwd=project, capture_output=True, text=True, timeout=30)
        out = r.stdout
        print("stdout:", repr(out))
        checks.append(("prints the greeting", "Hello, Alice!" in out, out.strip()))
        checks.append(("prints the verbose line", "Greeting completed." in out, out.strip()))
        checks.append(("exits cleanly", r.returncode == 0, f"exit={r.returncode}"))
    except Exception as e:
        checks.append(("the script runs", False, f"raised {e}"))

    # the old behaviour must still work
    try:
        r = subprocess.run([sys.executable, "greet.py", "Bob"], cwd=project,
                           capture_output=True, text=True, timeout=30)
        checks.append(("the plain call still works", "Hello, Bob!" in r.stdout,
                       r.stdout.strip()))
    except Exception as e:
        checks.append(("the plain call still works", False, f"raised {e}"))

    ok = all(c[1] for c in checks)
    for label, good, detail in checks:
        print(("ok  " if good else "FAIL"), label, "->", detail)
    print(json.dumps({"pass": ok, "checks": [c[0] for c in checks]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
