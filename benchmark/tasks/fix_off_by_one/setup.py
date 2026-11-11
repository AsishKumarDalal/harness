"""Fixture for the fix_off_by_one task: a function with an off-by-one bug."""

FILES = {
    "calc.py": '''"""A small arithmetic helper."""


def sum_range(start, end):
    """Return the sum of the integers from start to end, inclusive."""
    total = 0
    for i in range(start, end):
        total += i
    return total


if __name__ == "__main__":
    print(sum_range(1, 5))
''',
    "README.md": "# calc\n\nA tiny arithmetic helper used by the benchmark.\n",
}


def setup(project_dir):
    for name, content in FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
