#!/usr/bin/env python3
"""Check repository-relative Markdown file links without network access."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md"), *ROOT.glob("examples/*.md")]
    errors = []
    checked = 0
    for file in files:
        for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", file.read_text()):
            url = urlsplit(raw)
            if url.scheme or not url.path:
                continue
            checked += 1
            target = (file.parent / unquote(url.path)).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f"{file.relative_to(ROOT)}: broken local link")
    for error in errors:
        print(error)
    print(f"{'FAIL' if errors else 'PASS'}: {checked} local Markdown links")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
