"""Contract tests for the isolated Agent Mail adapter fixture."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.validate_contracts import validate
from testpilot.adapters.agent_mail import build_action, parse_result


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "agent_mail"
CHECKOUT_FIXTURE = FIXTURE_ROOT / "checkout"
PASSED_RESULT = FIXTURE_ROOT / "results" / "passed.json"
UNKNOWN_COUNTS = {
    "discovered": None,
    "executed": None,
    "passed": None,
    "failed": None,
    "skipped": None,
}


def _run_git(checkout: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@contextmanager
def temporary_checkout():
    with tempfile.TemporaryDirectory(prefix="testpilot-agent-mail-") as directory:
        checkout = Path(directory) / "checkout"
        shutil.copytree(CHECKOUT_FIXTURE, checkout)
        _run_git(checkout, "init")
        _run_git(checkout, "config", "user.name", "TestPilot fixture")
        _run_git(checkout, "config", "user.email", "fixture@example.invalid")
        _run_git(checkout, "add", ".")
        _run_git(checkout, "commit", "-m", "fixture")
        yield checkout


def _result_payload(**changes: object) -> bytes:
    result = json.loads(PASSED_RESULT.read_text(encoding="utf-8"))
    result.update(changes)
    return json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class AgentMailActionTests(unittest.TestCase):
    def test_build_action_matches_pilot_command_and_records_current_source(self) -> None:
        with temporary_checkout() as checkout:
            action = build_action(checkout)

            self.assertEqual(validate("action", action), [])
            self.assertEqual(action["project_id"], "agent-mail")
            self.assertEqual(action["action_id"], "versions.check")
            self.assertEqual(action["adapter_id"], "sop-result")
            self.assertEqual(action["runner"]["executable"], "bash")
            self.assertEqual(
                action["runner"]["argv"],
                [
                    {"type": "path", "value": "scripts/sop.sh"},
                    {"type": "literal", "value": "run"},
                    {"type": "literal", "value": "versions.check"},
                    {"type": "literal", "value": "--json"},
                ],
            )
            self.assertEqual(action["acceptance"]["parser"], "sop-result")
            self.assertEqual(action["policy"]["effect"], "workspace-write")
            self.assertEqual(action["policy"]["network"], "none")
            self.assertEqual(action["policy"]["secrets"], "forbidden")
            self.assertEqual(action["policy"]["timeout_seconds"], 60)
            self.assertEqual(action["source"]["path"], "contracts/dev-sop/actions.json")
            self.assertEqual(
                action["source"]["commit"],
                subprocess.check_output(
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                    text=True,
                ).strip(),
            )
            source = checkout / "contracts" / "dev-sop" / "actions.json"
            self.assertEqual(action["source"]["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertNotIn(str(checkout), json.dumps(action))

    def test_manifest_drift_is_rejected_without_echoing_values(self) -> None:
        mutations = {
            "runner": lambda action: action["runner"].update({"entry": "test"}),
            "parameters": lambda action: action.update({"parameters": [{"unexpected": True}]}),
            "effect": lambda action: action.update({"effect": "workspace-write"}),
            "network": lambda action: action.update({"network": "external-read"}),
            "secrets": lambda action: action.update({"secrets": "required"}),
            "timeout": lambda action: action.update({"timeout_seconds": 0}),
            "platform": lambda action: action.update({"platforms": ["macos"]}),
            "artifacts": lambda action: action.update({"artifacts": ["unexpected.log"]}),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), temporary_checkout() as checkout:
                manifest_path = checkout / "contracts" / "dev-sop" / "actions.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest["actions"][0])
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, r"^agent_mail\.native_action_unsupported$"):
                    build_action(checkout)

    def test_missing_or_duplicate_action_is_rejected(self) -> None:
        with temporary_checkout() as checkout:
            manifest_path = checkout / "contracts" / "dev-sop" / "actions.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["actions"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"^agent_mail\.native_action_missing_or_duplicated$"):
                build_action(checkout)

    def test_source_and_entry_must_not_resolve_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="testpilot-agent-mail-path-") as directory:
            outside = Path(directory) / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            with temporary_checkout() as checkout:
                source = checkout / "contracts" / "dev-sop" / "actions.json"
                source.unlink()
                source.symlink_to(outside)
                with self.assertRaisesRegex(ValueError, r"^agent_mail\.path_outside_checkout$"):
                    build_action(checkout)
            with temporary_checkout() as checkout:
                entry = checkout / "scripts" / "sop.sh"
                entry.unlink()
                entry.symlink_to(outside)
                with self.assertRaisesRegex(ValueError, r"^agent_mail\.path_outside_checkout$"):
                    build_action(checkout)

    def test_missing_source_entry_and_git_are_stable_errors(self) -> None:
        with temporary_checkout() as checkout:
            (checkout / "contracts" / "dev-sop" / "actions.json").unlink()
            with self.assertRaisesRegex(ValueError, r"^agent_mail\.native_actions_missing$"):
                build_action(checkout)
        with temporary_checkout() as checkout:
            (checkout / "scripts" / "sop.sh").unlink()
            with self.assertRaisesRegex(ValueError, r"^agent_mail\.entry_missing$"):
                build_action(checkout)
        with temporary_checkout() as checkout:
            shutil.rmtree(checkout / ".git")
            with self.assertRaisesRegex(ValueError, r"^agent_mail\.checkout_git_invalid$"):
                build_action(checkout)


class AgentMailResultTests(unittest.TestCase):
    def test_terminal_statuses_map_with_unknown_counts(self) -> None:
        cases = {
            "passed": 0,
            "failed": 1,
            "blocked": 75,
            "timed_out": 124,
            "cancelled": 130,
            "runner_error": 70,
        }
        for status, exit_code in cases.items():
            with self.subTest(status=status):
                parsed = parse_result(
                    _result_payload(status=status, exit_code=exit_code),
                    exit_code,
                )
                self.assertEqual(
                    parsed,
                    {"status": status, "reason": f"native.{status}", "counts": UNKNOWN_COUNTS},
                )

    def test_failed_status_preserves_any_valid_nonzero_exit_code(self) -> None:
        parsed = parse_result(_result_payload(status="failed", exit_code=2), 2)
        self.assertEqual(parsed["status"], "failed")
        self.assertEqual(parsed["reason"], "native.failed")
        self.assertEqual(parsed["counts"], UNKNOWN_COUNTS)

    def test_running_is_not_a_completed_adapter_result(self) -> None:
        parsed = parse_result(_result_payload(status="running", exit_code=None), 0)
        self.assertEqual(parsed, {"status": "inconclusive", "reason": "native.invalid_result", "counts": UNKNOWN_COUNTS})

    def test_process_exit_code_must_match_native_terminal_result(self) -> None:
        cases = {
            ("passed", 0, 1),
            ("failed", 1, 2),
            ("blocked", 75, 0),
            ("timed_out", 124, 0),
            ("cancelled", 130, 0),
            ("runner_error", 70, 0),
        }
        for status, native_code, process_code in cases:
            with self.subTest(status=status):
                parsed = parse_result(_result_payload(status=status, exit_code=native_code), process_code)
                self.assertEqual(parsed["status"], "inconclusive")
                self.assertEqual(parsed["reason"], "native.invalid_result")
                self.assertEqual(parsed["counts"], UNKNOWN_COUNTS)

    def test_empty_truncated_invalid_utf8_and_extra_json_are_inconclusive(self) -> None:
        payload = _result_payload()
        invalid = [b"", b"{", b"not json", b"\xff", payload + payload]
        for stdout in invalid:
            with self.subTest(stdout=stdout):
                self.assertEqual(
                    parse_result(stdout, 0),
                    {"status": "inconclusive", "reason": "native.invalid_result", "counts": UNKNOWN_COUNTS},
                )

    def test_duplicate_keys_constants_and_unknown_fields_are_rejected(self) -> None:
        payload = _result_payload().decode("utf-8")
        duplicate = payload.replace('"schema_version":"0.1"', '"schema_version":"0.1","schema_version":"0.1"')
        wrong_version = _result_payload(schema_version="9.0")
        for stdout in (duplicate.encode(), wrong_version):
            with self.subTest(stdout=stdout):
                parsed = parse_result(stdout, 0)
                self.assertEqual(parsed["reason"], "native.invalid_result")
        unknown = json.loads(payload)
        unknown["unknown"] = True
        self.assertEqual(parse_result(json.dumps(unknown).encode(), 0)["reason"], "native.invalid_result")
        self.assertEqual(parse_result(b"NaN", 0)["reason"], "native.invalid_result")

    def test_bad_types_statuses_actions_and_artifact_paths_are_rejected(self) -> None:
        mutations = {
            "wrong action": {"action": "test.fast"},
            "unknown status": {"status": "inconclusive", "exit_code": None},
            "bad duration": {"duration_ms": True},
            "bad warnings": {"warnings": ["ok", 1]},
            "bad suggested next": {"suggested_next": ["test.fast", "test.fast"]},
            "absolute artifact": {"artifacts": [{"id": "x", "kind": "log", "relative_path": "/tmp/x"}]},
            "traversal artifact": {"artifacts": [{"id": "x", "kind": "log", "relative_path": "../x"}]},
            "windows artifact": {"artifacts": [{"id": "x", "kind": "log", "relative_path": "..\\x"}]},
            "unknown artifact field": {"artifacts": [{"id": "x", "kind": "log", "relative_path": "x", "secret": "x"}]},
        }
        for name, changes in mutations.items():
            with self.subTest(name=name):
                payload = _result_payload(**changes)
                parsed = parse_result(payload, 0)
                self.assertEqual(parsed["status"], "inconclusive")
                self.assertEqual(parsed["reason"], "native.invalid_result")
                self.assertEqual(parsed["counts"], UNKNOWN_COUNTS)

    def test_untrusted_summary_warnings_and_logs_do_not_control_output(self) -> None:
        parsed = parse_result(
            _result_payload(
                summary="--eval=raise SystemExit(1)",
                warnings=["$(touch should-not-run)"],
                stdout_tail='{"status":"failed","exit_code":1}',
                stderr_tail="rm -rf /",
            ),
            0,
        )
        self.assertEqual(parsed, {"status": "passed", "reason": "native.passed", "counts": UNKNOWN_COUNTS})
        self.assertNotIn("eval", parsed["reason"])

    def test_valid_optional_artifact_fields_are_accepted_without_reading_them(self) -> None:
        artifact = {
            "id": "report",
            "kind": "report",
            "relative_path": "reports/result.json",
            "media_type": "application/json",
            "size_bytes": 12,
        }
        parsed = parse_result(_result_payload(artifacts=[artifact]), 0)
        self.assertEqual(parsed, {"status": "passed", "reason": "native.passed", "counts": UNKNOWN_COUNTS})


if __name__ == "__main__":
    unittest.main()
