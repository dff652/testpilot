#!/usr/bin/env python3
"""Run TestPilot directly from its source checkout."""
from pathlib import Path
import os
import sys

if sys.platform == "linux" and sys.getfilesystemencoding().lower() != "utf-8":
    os.execv(sys.executable, [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from testpilot.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
