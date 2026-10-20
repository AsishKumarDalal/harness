"""cli.py — the `harness` command.

    cd ~/projects/my-app && harness        # work on the folder you are in
    harness ~/projects/other               # work on another folder
    harness --project ~/projects/other

The project folder is where the agent reads and writes. The harness' own
state (notebook, safety rules, exports) stays in HARNESS_HOME, outside it.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True      # keep __pycache__ out of the project folder

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="harness",
        description="The Harness — an agentic coding CLI. "
                    "Runs on the current folder unless you name another one.",
        allow_abbrev=False,
    )
    p.add_argument("folder", nargs="?", default=None,
                   help="project folder to work on (default: the current folder)")
    p.add_argument("-p", "--project", dest="project", default=None,
                   help="project folder to work on (same as the positional argument)")
    p.add_argument("-m", "--model", dest="model", default=None,
                   help="model to use for this run (overrides .env)")
    p.add_argument("-v", "--version", action="version",
                   version=f"harness (model: {config.MODEL})")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    target = args.project or args.folder
    if target:
        path = Path(target).expanduser()
        if not path.is_dir():
            print(f"not a folder: {path}")
            return 1
        config.set_project_dir(path)

    if args.model:
        config.MODEL = args.model

    import main as app          # imported AFTER the project dir is settled
    app.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
