"""tui/__main__.py — `python -m tui` starts the Textual front-end.

    python -m tui                 # work on the current folder
    python -m tui ~/projects/app  # work on another folder
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tui.app import HarnessApp  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Entry point: `python -m tui [project] [--model NAME]`."""
    args = list(sys.argv[1:] if argv is None else argv)
    model: str | None = None
    project: str | None = None

    while args:
        arg = args.pop(0)
        if arg in ("-m", "--model") and args:
            model = args.pop(0)
        elif arg.startswith("--model="):
            model = arg.split("=", 1)[1]
        elif arg.startswith("-"):
            print(f"unknown option: {arg}")
            return 2
        else:
            project = arg

    if project and not Path(project).expanduser().is_dir():
        print(f"not a folder: {project}")
        return 1

    HarnessApp(model=model, project=project).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
