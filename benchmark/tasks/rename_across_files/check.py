"""Check the rename_across_files task: the old name must be gone, the new one must work."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    p = Path(project)
    checks = []

    # the old name must be gone from every source file
    leftovers = []
    for f in sorted(p.glob("*.py")):
        text = f.read_text(encoding="utf-8")
        if "calculate_total" in text:
            leftovers.append(f.name)
    checks.append(("the old name is gone everywhere", not leftovers, str(leftovers)))

    # the new name must be used
    new_used = any("compute_total" in f.read_text(encoding="utf-8")
                   for f in p.glob("*.py"))
    checks.append(("the new name is used", new_used, ""))

    # and the code must still work
    try:
        r = subprocess.run([sys.executable, "-c",
                            "import b, c; print(b.basket_total(), c.items_total())"],
                           cwd=project, capture_output=True, text=True, timeout=30)
        checks.append(("the modules still import and run",
                       r.returncode == 0 and "60" in r.stdout,
                       (r.stdout + r.stderr).strip()))
    except Exception as e:
        checks.append(("the modules still import and run", False, f"raised {e}"))

    ok = all(c[1] for c in checks)
    for label, good, detail in checks:
        print(("ok  " if good else "FAIL"), label, "->", detail)
    print(json.dumps({"pass": ok, "checks": [c[0] for c in checks]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
