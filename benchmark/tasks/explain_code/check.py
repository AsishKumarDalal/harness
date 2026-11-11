"""Check the explain_code task: the answer must mention what transform does.

This task expects NO file changes — only a correct answer, so the checker
reads the agent's final answer instead of the project.
"""

import json
import sys


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "."
    answer = sys.argv[2] if len(sys.argv) > 2 else ""
    low = answer.lower()

    checks = [
        ("the answer mentions uppercasing", "upper" in low, ""),
        ("the answer mentions the name field", "name" in low, ""),
        ("the answer is not empty", bool(answer.strip()), ""),
    ]

    # the project must be untouched (this task only asks a question)
    try:
        text = open(f"{project}/pipeline.py", encoding="utf-8").read()
        checks.append(("the file was not modified",
                       ".upper()" in text, ""))
    except Exception as e:
        checks.append(("the file was not modified", False, f"raised {e}"))

    ok = all(c[1] for c in checks)
    for label, good, detail in checks:
        print(("ok  " if good else "FAIL"), label, "->", detail)
    print(json.dumps({"pass": ok, "checks": [c[0] for c in checks]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
