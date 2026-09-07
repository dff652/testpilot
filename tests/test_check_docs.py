"""Regression tests for repository-relative Markdown link checking."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import scripts.check_docs as check_docs


class CheckDocsTests(unittest.TestCase):
    def run_checker(self, files):
        with tempfile.TemporaryDirectory(prefix="testpilot-check-docs-") as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            for relative, content in files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            original_root = check_docs.ROOT
            output = StringIO()
            try:
                check_docs.ROOT = root
                with redirect_stdout(output):
                    result = check_docs.main()
            finally:
                check_docs.ROOT = original_root
            return result, output.getvalue()

    def test_valid_titles_and_angle_destinations(self):
        result, output = self.run_checker({
            "README.md": (
                "[plain](docs/target.md)\n"
                "[title](docs/target.md \"a title\")\n"
                "[space](<docs/target file.md> 'a title')\n"
            ),
            "docs/target.md": "# target\n",
            "docs/target file.md": "# target\n",
        })
        self.assertFalse(result)
        self.assertIn("PASS: 3 local Markdown links", output)

    def test_missing_target_with_title_is_rejected(self):
        result, output = self.run_checker({
            "README.md": '[missing](docs/missing.md "title")\n',
        })
        self.assertTrue(result)
        self.assertIn("README.md: broken local link", output)
        self.assertIn("FAIL: 1 local Markdown links", output)

    def test_non_utf8_cli_accepts_chinese_target(self):
        with tempfile.TemporaryDirectory(prefix="testpilot-check-docs-cli-") as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            docs = root / "docs"
            scripts.mkdir()
            docs.mkdir()
            shutil.copy2(Path(check_docs.__file__), scripts / "check_docs.py")
            (root / "README.md").write_text(
                '[故障记录](<docs/中文 记录.md> "title")\n',
                encoding="utf-8",
            )
            (docs / "中文 记录.md").write_text("# fixture\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update({
                "LC_ALL": "C",
                "LANG": "C",
                "PYTHONCOERCECLOCALE": "0",
                "PYTHONUTF8": "0",
            })
            completed = subprocess.run(
                [sys.executable, str(scripts / "check_docs.py")],
                cwd=root,
                env=environment,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", "replace"),
            )
            self.assertIn("PASS: 1 local Markdown links", completed.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
