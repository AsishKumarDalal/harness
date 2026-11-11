"""Check the fix_off_by_one task: sum_range(1, 5) must be 15."""

import json
import sys


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    sys.path.insert(0, project)
    try:
        import calc
    except Exception as e:
        print(f"FAIL: could not import calc.py: {e}")
        print(json.dumps({"pass": False, "why": f"import failed: {e}"}))
        return 1

    checks = []
    try:
        got = calc.sum_range(1, 5)
        checks.append(("sum_range(1, 5) == 15", got == 15, f"got {got}"))
    except Exception as e:
        checks.append(("sum_range(1, 5) == 15", False, f"raised {e}"))

    try:
        got = calc.sum_range(0, 0)
        checks.append(("sum_range(0, 0) == 0", got == 0, f"got {got}"))
    except Exception as e:
        checks.append(("sum_range(0, 0) == 0", False, f"raised {e}"))

    ok = all(c[1] for c in checks)
    for label, good, detail in checks:
        print(("ok  " if good else "FAIL"), label, detail)
    print(json.dumps({"pass": ok, "checks": [c[0] for c in checks]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
