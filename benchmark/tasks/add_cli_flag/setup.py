"""Fixture for the add_cli_flag task: a script that needs a --verbose flag."""

FILES = {
    "greet.py": '''"""Greet someone from the command line."""

import sys


def greet(name):
    """Return the greeting for a name."""
    return f"Hello, {name}!"


def main(argv):
    name = argv[0] if argv else "world"
    print(greet(name))


if __name__ == "__main__":
    main(sys.argv[1:])
''',
    "README.md": "# greet\n\nA command line greeter.\n",
}


def setup(project_dir):
    for name, content in FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
