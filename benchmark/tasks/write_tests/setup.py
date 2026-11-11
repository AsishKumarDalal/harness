"""Fixture for the write_tests task: a function the agent must write tests for."""

FILES = {
    "mathlib.py": '''"""A small number-theory helper."""


def is_prime(n):
    """Return True if n is a prime number."""
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True
''',
    "README.md": "# mathlib\n\nA small number-theory helper.\n",
}


def setup(project_dir):
    for name, content in FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
