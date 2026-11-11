"""Check the write_tests task: the test file must exist and pass."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    p = Path(project)
    checks = []

    test_file = p / "test_mathlib.py"
    checks.append(("the test file exists", test_file.exists(), str(test_file)))
    if test_file.exists():
        try:
            r = subprocess.run([sys.executable, "test_mathlib.py"], cwd=project,
                               capture_output=True, text=True, timeout=60)
            checks.append(("the tests pass", r.returncode == 0,
                           (r.stdout + r.stderr).strip()[-300:]))
        except Exception as e:
            checks.append(("the tests pass", False, f"raised {e}"))

        # the tests must actually cover the cases
        text = test_file.read_text(encoding="utf-8")
        for case in ("is_prime(2)", "is_prime(4)", "is_prime(1)"):
            checks.append((f"covers {case}", case in text.replace(" ", ""), ""))
        checks.append(("uses plain asserts", "assert" in text, ""))

    ok = all(c[1] for c in checks)
    for label, good, detail in checks:
        print(("ok  " if good else "FAIL"), label, "->", detail)
    print(json.dumps({"pass": ok, "checks": [c[0] for c in checks]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
