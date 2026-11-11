"""Fixture for the explain_code task: a question that needs reading, not writing."""

FILES = {
    "pipeline.py": '''"""A tiny data pipeline."""


def transform(rows):
    """Normalise a list of row dicts into uppercase names."""
    out = []
    for row in rows:
        name = row.get("name", "")
        out.append(name.upper())
    return out


def run(rows):
    """Transform the rows and drop the empty ones."""
    return [r for r in transform(rows) if r]
''',
    "README.md": "# pipeline\n\nA tiny data pipeline.\n",
}


def setup(project_dir):
    for name, content in FILES.items():
        (project_dir / name).write_text(content, encoding="utf-8")
