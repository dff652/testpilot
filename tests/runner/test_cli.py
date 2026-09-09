"""Black-box CLI acceptance tests using an isolated synthetic Git checkout."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "testpilot.py"
RESULT_SCHEMA = json.loads(
    (ROOT / "contracts" / "result.schema.json").read_text(encoding="utf-8")
)


FIXTURE_SOURCE = '''\
#!/usr/bin/env python3
import json
from pathlib import Path
import sys


def emit(status="passed", discovered=2, executed=2, passed=2, failed=0, skipped=0):
    print(json.dumps({
        "status": status,
        "counts": {
            "discovered": discovered,
            "executed": executed,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
    }, separators=(",", ":"), sort_keys=True))


mode = sys.argv[1] if len(sys.argv) > 1 else "passed"
if mode == "no-output":
    raise SystemExit(0)
if mode == "zero":
    emit(discovered=0, executed=0, passed=0, failed=0, skipped=0)
    raise SystemExit(0)
if mode == "fail":
    emit(status="failed", passed=1, failed=1)
    raise SystemExit(7)
if mode == "argv":
    Path("argv-seen.json").write_text(
        json.dumps(sys.argv[2:], ensure_ascii=True), encoding="utf-8"
    )
if mode == "mark":
    Path(sys.argv[2]).write_text("ran", encoding="utf-8")
emit()
'''


def run_checked(command, *, cwd, env, timeout=30):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


class TestPilotCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="testpilot-cli-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "checkout"
        self.home = self.root / "home"
        self.repo.mkdir()
        self.home.mkdir()
        (self.repo / "scripts").mkdir()
        (self.repo / "docs").mkdir()
        (self.repo / "scripts" / "fixture.py").write_text(
            FIXTURE_SOURCE, encoding="utf-8"
        )
        (self.repo / "docs" / "source.md").write_text(
            "# Synthetic fixture source\n", encoding="utf-8"
        )
        self.git(["init", "-q"])
        self.git(["config", "user.name", "TestPilot fixture"])
        self.git(["config", "user.email", "testpilot-fixture@example.invalid"])
        self.git(["add", "."])
        self.git(["commit", "-qm", "initial fixture"])
        self.registry = self.root / "registry.json"

    def tearDown(self):
        self.temp.cleanup()

    def environment(self):
        environment = os.environ.copy()
        environment.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        return environment

    def git(self, args):
        completed = run_checked(
            ["git", "-C", str(self.repo), *args],
            cwd=ROOT,
            env=self.environment(),
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        return completed

    def cli(self, *args, timeout=30):
        return run_checked(
            [sys.executable, str(CLI), *map(str, args)],
            cwd=ROOT,
            env=self.environment(),
            timeout=timeout,
        )

    def action(
        self,
        action_id="test.synthetic",
        *,
        mode="passed",
        entry="scripts/fixture.py",
        source_path="docs/source.md",
        required_artifacts=("report.json",),
        extra_args=(),
    ):
        source = self.repo / source_path
        action = {
            "schema_version": "0.1.0",
            "project_id": "fixture",
            "action_id": action_id,
            "adapter_id": "fixture",
            "kind": "test",
            "runner": {
                "executable": "python3",
                "argv": [
                    {"type": "path", "value": entry},
                    {"type": "literal", "value": mode},
                    *[
                        {"type": "literal", "value": value}
                        for value in extra_args
                    ],
                ],
                "cwd": ".",
            },
            "policy": {
                "effect": "workspace-write",
                "network": "none",
                "secrets": "forbidden",
                "platforms": ["linux"],
                "timeout_seconds": 10,
                "locks": ["git-common-dir"],
                "prerequisites": [],
            },
            "acceptance": {
                "parser": "fixture-json",
                "required_artifacts": list(required_artifacts),
                "require_test_counts": True,
            },
            "source": {
                "path": source_path,
                "commit": self.git(["rev-parse", "HEAD"]).stdout.decode().strip(),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
        }
        action_file = self.root / f"{action_id.replace('.', '-')}.action.json"
        action_file.write_text(
            json.dumps(action, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return action_file

    def register(self, action_file):
        completed = self.cli(
            "register",
            "--registry",
            self.registry,
            "--checkout-id",
            "fixture-main",
            "--project-id",
            "fixture",
            "--checkout",
            self.repo,
            "--action",
            action_file,
            "--tool",
            f"python3={sys.executable}",
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr.decode("utf-8", "replace"),
        )
        output = completed.stdout.decode("utf-8")
        self.assertIn("registered", output)
        return completed

    def run_action(self, action_id="test.synthetic", run_id=None):
        args = [
            "run",
            "--registry",
            self.registry,
            "--checkout-id",
            "fixture-main",
            "--action-id",
            action_id,
        ]
        if run_id is not None:
            args.extend(["--run-id", run_id])
        return self.cli(*args)

    def result(self, completed):
        self.assertTrue(completed.stdout, completed.stderr.decode("utf-8", "replace"))
        try:
            result = json.loads(completed.stdout.decode("utf-8"))
        except json.JSONDecodeError as error:
            self.fail(
                f"CLI did not emit one JSON result: {error}; "
                f"stdout={completed.stdout!r}"
            )
        errors = sorted(
            Draft202012Validator(
                RESULT_SCHEMA, format_checker=FormatChecker()
            ).iter_errors(result),
            key=lambda error: list(error.absolute_path),
        )
        self.assertFalse(
            errors,
            "; ".join(error.message for error in errors),
        )
        return result

    def test_register_run_status_and_cancel_lifecycle(self):
        action_file = self.action()
        self.register(action_file)

        completed = self.run_action(run_id="run.lifecycle")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        result = self.result(completed)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["project_id"], "fixture")
        self.assertEqual(result["action_id"], "test.synthetic")
        self.assertEqual(result["run_id"], "run.lifecycle")
        self.assertEqual(result["counts"]["executed"], 2)

        status = self.cli(
            "status",
            "--registry",
            self.registry,
            "--checkout-id",
            "fixture-main",
            "--run-id",
            result["run_id"],
            "--attempt-id",
            result["attempt_id"],
        )
        self.assertEqual(status.returncode, 0, status.stderr.decode("utf-8", "replace"))
        self.assertEqual(self.result(status), result)

        cancel = self.cli(
            "cancel",
            "--registry",
            self.registry,
            "--checkout-id",
            "fixture-main",
            "--run-id",
            result["run_id"],
            "--attempt-id",
            result["attempt_id"],
        )
        self.assertEqual(cancel.returncode, 0, cancel.stderr.decode("utf-8", "replace"))
        cancel_payload = json.loads(cancel.stdout.decode("utf-8"))
        self.assertIsInstance(cancel_payload.get("cancel_requested"), bool)
        self.assertFalse(cancel_payload["cancel_requested"])

    def test_literal_argv_is_passed_without_shell(self):
        marker = self.root / "shell-marker"
        punctuation = f"$(touch {marker}) ; &"
        action_file = self.action(mode="argv", extra_args=(punctuation,))
        self.register(action_file)

        completed = self.run_action()
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        result = self.result(completed)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(marker.exists())
        self.assertEqual(
            json.loads((self.repo / "argv-seen.json").read_text(encoding="utf-8")),
            [punctuation],
        )

    def test_same_run_id_creates_distinct_attempts_and_preserves_status(self):
        self.register(self.action())
        first = self.run_action(run_id="run.reused")
        second = self.run_action(run_id="run.reused")
        self.assertEqual(first.returncode, 0, first.stderr.decode("utf-8", "replace"))
        self.assertEqual(second.returncode, 0, second.stderr.decode("utf-8", "replace"))
        first_result = self.result(first)
        second_result = self.result(second)
        self.assertEqual(first_result["run_id"], second_result["run_id"])
        self.assertNotEqual(first_result["attempt_id"], second_result["attempt_id"])
        for expected in (first_result, second_result):
            status = self.cli(
                "status",
                "--registry",
                self.registry,
                "--checkout-id",
                "fixture-main",
                "--run-id",
                expected["run_id"],
                "--attempt-id",
                expected["attempt_id"],
            )
            self.assertEqual(status.returncode, 0, status.stderr.decode("utf-8", "replace"))
            self.assertEqual(self.result(status), expected)

    def test_unregistered_action_is_rejected_without_execution(self):
        marker = self.root / "unregistered-marker"
        self.register(
            self.action(
                action_id="test.registered",
                mode="mark",
                extra_args=(str(marker),),
            )
        )
        completed = self.run_action(action_id="test.unregistered")
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(marker.exists())

    def test_source_entrypoint_drift_is_blocked(self):
        action_file = self.action(source_path="scripts/fixture.py")
        self.register(action_file)
        entry = self.repo / "scripts" / "fixture.py"
        entry.write_text(
            entry.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8"
        )

        completed = self.run_action()
        self.assertEqual(completed.returncode, 2, completed.stderr.decode("utf-8", "replace"))
        result = self.result(completed)
        self.assertEqual(result["status"], "blocked")

    def test_typed_path_symlink_escape_is_blocked(self):
        marker = self.root / "outside-ran"
        outside = self.root / "outside.py"
        outside.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('ran', encoding='utf-8')\n"
            "print('{\"status\":\"passed\",\"counts\":{\"discovered\":2,\"executed\":2,\"passed\":2,\"failed\":0,\"skipped\":0}}')\n",
            encoding="utf-8",
        )
        self.register(self.action(entry="scripts/fixture.py"))
        (self.repo / "scripts" / "fixture.py").unlink()
        (self.repo / "scripts" / "fixture.py").symlink_to(outside)

        completed = self.run_action()
        self.assertEqual(completed.returncode, 2, completed.stderr.decode("utf-8", "replace"))
        result = self.result(completed)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(marker.exists())

    def test_zero_tests_and_missing_report_are_not_passed(self):
        zero = self.action(action_id="test.zero", mode="zero")
        missing = self.action(
            action_id="test.missing",
            mode="no-output",
            required_artifacts=("report.json",),
        )
        self.register(zero)
        self.register(missing)

        zero_result = self.result(self.run_action("test.zero"))
        missing_result = self.result(self.run_action("test.missing"))
        self.assertNotEqual(zero_result["status"], "passed")
        self.assertNotEqual(missing_result["status"], "passed")
        self.assertIn("report.json", missing_result["missing_artifacts"])

    def test_nonzero_process_is_not_passed(self):
        self.register(self.action(mode="fail"))
        completed = self.run_action()
        self.assertNotEqual(completed.returncode, 0)
        result = self.result(completed)
        self.assertNotEqual(result["status"], "passed")
        self.assertEqual(result["exit_code"], 7)


if __name__ == "__main__":
    unittest.main()
