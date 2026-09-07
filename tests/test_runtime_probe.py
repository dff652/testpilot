"""Regression tests for the standalone synthetic runtime probe."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "runtime_probe.py"


class RuntimeProbeTests(unittest.TestCase):
    def test_non_utf8_parent_and_missing_node(self):
        environment = os.environ.copy()
        environment.update({
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": "0",
            "PATH": "/nonexistent",
        })
        completed = subprocess.run(
            [sys.executable, str(PROBE)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        summary = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(summary["overall_status"], "passed")
        self.assertEqual(summary["checks"]["python"]["status"], "passed")
        self.assertEqual(summary["checks"]["node"]["status"], "not_available")
        self.assertEqual(summary["checks"]["markdown"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
