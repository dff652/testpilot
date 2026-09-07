#!/usr/bin/env python3
"""Check repository-relative Markdown file links without network access."""
from pathlib import Path
import os
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
UTF8_REEXEC_ENV = "TESTPILOT_CHECK_DOCS_UTF8"
LINK_RE = re.compile(
    r"""\[[^\]\n]*\]\(\s*
        (?P<destination><[^>\n]*>|[^\s)]+)
        (?:\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\)))?
        \s*\)""",
    re.VERBOSE,
)


def ensure_utf8_runtime():
    """Re-exec the CLI when the parent selected a non-UTF-8 locale."""
    if os.environ.get(UTF8_REEXEC_ENV) == "1":
        return
    encodings = (
        sys.getfilesystemencoding(),
        sys.stdout.encoding,
        sys.stderr.encoding,
    )
    if all((encoding or "").casefold().replace("-", "").replace("_", "") == "utf8"
           for encoding in encodings):
        return
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment[UTF8_REEXEC_ENV] = "1"
    script = os.path.abspath(__file__)
    os.execve(sys.executable, [sys.executable, script, *sys.argv[1:]], environment)


def main():
    files = [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md"), *ROOT.glob("examples/*.md")]
    errors = []
    checked = 0
    for file in files:
        for match in LINK_RE.finditer(file.read_text(encoding="utf-8")):
            destination = match.group("destination")
            if destination.startswith("<") and destination.endswith(">"):
                destination = destination[1:-1]
            url = urlsplit(destination)
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
    ensure_utf8_runtime()
    raise SystemExit(main())
