"""Fixture for the rename_across_files task: one function used in three files."""

FILES = {
    "a.py": '''"""The original implementation."""


def calculate_total(prices):
    """Return the total of a list of prices."""
    total = 0
    for price in prices:
        total += price
    return total
''',
    "b.py": '''"""A consumer of the original implementation."""

from a import calculate_total

PRICES = [10, 20, 30]


def basket_total():
    return calculate_total(PRICES)
''',
    "c.py": '''"""Another consumer of the original implementation."""

from a import calculate_total

ITEMS = [1.5, 2.5]


def items_total():
    return calculate_total(ITEMS)
''',
    "README.md": "# prices\n\nA tiny pricing module used by the benchmark.\n",
}


def setup(project_dir):
    for name, content in FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
