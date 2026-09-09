#!/usr/bin/env python3
"""Compatibility entrypoint for offline contract validation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from testpilot.contracts import KINDS, main, validate  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())
