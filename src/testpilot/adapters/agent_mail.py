"""Safe adapter for Agent Mail's read-only ``versions.check`` SOP action."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any


_ACTION_ID = "versions.check"
_SOURCE_RELATIVE = Path("contracts/dev-sop/actions.json")
_ENTRY_RELATIVE = Path("scripts/sop.sh")
_ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9-]+)*$")
_RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9_-]+$")
_DATETIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
    r"[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_ARTIFACT_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_NATIVE_ACTION_KEYS = {
    "id",
    "description",
    "runner",
    "parameters",
    "timeout_seconds",
    "effect",
    "network",
    "secrets",
    "platforms",
    "artifacts",
    "ci_required",
    "mcp_phase",
}
_NATIVE_RESULT_KEYS = {
    "schema_version",
    "run_id",
    "action",
    "status",
    "exit_code",
    "started_at",
    "duration_ms",
    "summary",
    "warnings",
    "stdout_tail",
    "stderr_tail",
    "artifacts",
    "suggested_next",
}
_NATIVE_RESULT_STATUSES = {
    "running",
    "passed",
    "failed",
    "blocked",
    "cancelled",
    "timed_out",
    "runner_error",
}
_NATIVE_RESULT_TERMINAL_CODES = {
    "passed": 0,
    "blocked": 75,
    "cancelled": 130,
    "timed_out": 124,
    "runner_error": 70,
}
_NATIVE_ARTIFACT_KEYS = {"id", "kind", "relative_path", "media_type", "size_bytes"}
_NATIVE_ARTIFACT_KINDS = {"log", "report", "package", "coverage", "other"}


def _fail(reason: str) -> None:
    """Raise a stable error without copying untrusted values into its text."""

    raise ValueError(f"agent_mail.{reason}")


def _inside_checkout(root: Path, relative: Path, missing_reason: str) -> Path:
    candidate = root / relative
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        _fail(missing_reason)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail("path_outside_checkout")
    return resolved


def _checkout_root(checkout: Path) -> Path:
    try:
        root = Path(checkout).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        _fail("checkout_invalid")
    if not root.is_dir():
        _fail("checkout_invalid")
    return root


def _read_json_object(path: Path, reason: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _fail(reason)
    if not isinstance(document, dict):
        _fail(reason)
    return document


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_native_action(action: Any) -> bool:
    if not isinstance(action, dict) or set(action) != _NATIVE_ACTION_KEYS:
        return False
    if action.get("id") != _ACTION_ID:
        return False
    if not isinstance(action.get("description"), str) or not action["description"]:
        return False
    runner = action.get("runner")
    if not isinstance(runner, dict) or set(runner) != {"kind", "entry", "aliases"}:
        return False
    if runner.get("kind") != "sop" or runner.get("entry") != "versions":
        return False
    if not isinstance(runner.get("aliases"), list) or runner["aliases"] != []:
        return False
    if action.get("parameters") != []:
        return False
    timeout = action.get("timeout_seconds")
    if not _is_int(timeout) or not 1 <= timeout <= 3600:
        return False
    if action.get("effect") != "inspect":
        return False
    if action.get("network") != "none" or action.get("secrets") != "forbidden":
        return False
    platforms = action.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        return False
    if not all(isinstance(platform, str) for platform in platforms):
        return False
    if len(set(platforms)) != len(platforms):
        return False
    if any(platform not in {"linux", "macos", "windows-wsl"} for platform in platforms):
        return False
    if "linux" not in platforms:
        return False
    if action.get("artifacts") != []:
        return False
    if action.get("ci_required") is not False or action.get("mcp_phase") != "mcp0":
        return False
    return True


def _native_action(document: dict[str, Any]) -> dict[str, Any]:
    if set(document) != {"$schema", "schema_version", "description", "actions"}:
        _fail("native_actions_invalid")
    if not isinstance(document.get("$schema"), str):
        _fail("native_actions_invalid")
    if document.get("schema_version") != "0.1":
        _fail("native_actions_invalid")
    if not isinstance(document.get("description"), str) or not document["description"]:
        _fail("native_actions_invalid")
    actions = document.get("actions")
    if not isinstance(actions, list):
        _fail("native_actions_invalid")
    matches = [action for action in actions if isinstance(action, dict) and action.get("id") == _ACTION_ID]
    if len(matches) != 1:
        _fail("native_action_missing_or_duplicated")
    if not _valid_native_action(matches[0]):
        _fail("native_action_unsupported")
    return matches[0]


def _git_head(checkout: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        commit = completed.stdout.decode("ascii").strip()
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        _fail("checkout_git_invalid")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        _fail("checkout_git_invalid")
    return commit


def build_action(checkout: Path) -> dict[str, Any]:
    """Build the fixed TestPilot action from a verified Agent Mail checkout."""

    root = _checkout_root(checkout)
    source = _inside_checkout(root, _SOURCE_RELATIVE, "native_actions_missing")
    entry = _inside_checkout(root, _ENTRY_RELATIVE, "entry_missing")
    if not source.is_file():
        _fail("native_actions_missing")
    if not entry.is_file():
        _fail("entry_missing")
    document = _read_json_object(source, "native_actions_invalid")
    native_action = _native_action(document)
    commit = _git_head(root)
    try:
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    except OSError:
        _fail("native_actions_unreadable")
    timeout = native_action["timeout_seconds"]
    return {
        "schema_version": "0.1.0",
        "project_id": "agent-mail",
        "action_id": _ACTION_ID,
        "adapter_id": "sop-result",
        "kind": "check",
        "runner": {
            "executable": "bash",
            "argv": [
                {"type": "path", "value": "scripts/sop.sh"},
                {"type": "literal", "value": "run"},
                {"type": "literal", "value": _ACTION_ID},
                {"type": "literal", "value": "--json"},
            ],
            "cwd": ".",
        },
        "policy": {
            "effect": "workspace-write",
            "network": "none",
            "secrets": "forbidden",
            "platforms": ["linux"],
            "timeout_seconds": timeout,
            "locks": ["git-common-dir"],
            "prerequisites": [
                "Python3; complete native checkout",
                "Native runner writes and prunes .agent-mail/dev-sop records",
            ],
        },
        "acceptance": {
            "parser": "sop-result",
            "required_artifacts": ["native-output.log"],
            "require_test_counts": False,
        },
        "source": {
            "path": str(_SOURCE_RELATIVE),
            "commit": commit,
            "sha256": source_hash,
        },
    }


def _unknown_counts() -> dict[str, None]:
    return {
        "discovered": None,
        "executed": None,
        "passed": None,
        "failed": None,
        "skipped": None,
    }


def _invalid_result() -> dict[str, Any]:
    return {
        "status": "inconclusive",
        "reason": "native.invalid_result",
        "counts": _unknown_counts(),
    }


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not _DATETIME_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith(("/", "\\")) or ":" in value or "\\" in value:
        return False
    if any(part == ".." for part in value.split("/")):
        return False
    return all(ord(char) >= 0x20 for char in value)


def _valid_artifact(value: Any) -> bool:
    if not isinstance(value, dict) or not set(value).issubset(_NATIVE_ARTIFACT_KEYS):
        return False
    if not {"id", "kind", "relative_path"}.issubset(value):
        return False
    if not isinstance(value["id"], str) or not _ARTIFACT_ID_RE.fullmatch(value["id"]):
        return False
    if not isinstance(value["kind"], str) or value["kind"] not in _NATIVE_ARTIFACT_KINDS:
        return False
    if not _valid_relative_path(value["relative_path"]):
        return False
    if "media_type" in value and (
        not isinstance(value["media_type"], str) or not value["media_type"]
    ):
        return False
    if "size_bytes" in value and (
        not _is_int(value["size_bytes"]) or value["size_bytes"] < 0
    ):
        return False
    return True


def _valid_native_result(document: Any) -> bool:
    if not isinstance(document, dict) or set(document) != _NATIVE_RESULT_KEYS:
        return False
    if document.get("schema_version") != "0.1":
        return False
    if not isinstance(document.get("run_id"), str) or not _RUN_ID_RE.fullmatch(document["run_id"]):
        return False
    if document.get("action") != _ACTION_ID:
        return False
    status = document.get("status")
    if not isinstance(status, str) or status not in _NATIVE_RESULT_STATUSES:
        return False
    exit_code = document.get("exit_code")
    if exit_code is not None and (not _is_int(exit_code) or not 0 <= exit_code <= 255):
        return False
    if status == "running":
        if exit_code is not None:
            return False
    elif status == "failed":
        if exit_code is None or not 1 <= exit_code <= 255:
            return False
    elif exit_code != _NATIVE_RESULT_TERMINAL_CODES[status]:
        return False
    if not _valid_datetime(document.get("started_at")):
        return False
    if not _is_int(document.get("duration_ms")) or document["duration_ms"] < 0:
        return False
    if not isinstance(document.get("summary"), str):
        return False
    if not isinstance(document.get("warnings"), list) or not all(
        isinstance(item, str) for item in document["warnings"]
    ):
        return False
    if not isinstance(document.get("stdout_tail"), str):
        return False
    if not isinstance(document.get("stderr_tail"), str):
        return False
    artifacts = document.get("artifacts")
    if not isinstance(artifacts, list) or not all(_valid_artifact(item) for item in artifacts):
        return False
    suggested_next = document.get("suggested_next")
    if not isinstance(suggested_next, list) or not all(
        isinstance(item, str) and _ACTION_ID_RE.fullmatch(item) for item in suggested_next
    ):
        return False
    return len(set(suggested_next)) == len(suggested_next)


def parse_result(stdout: bytes, process_exit_code: int) -> dict[str, Any]:
    """Map one complete native result object to a count-free TestPilot result."""

    invalid = _invalid_result()
    if not isinstance(stdout, bytes) or not _is_int(process_exit_code):
        return invalid
    if not 0 <= process_exit_code <= 255:
        return invalid
    try:
        document = json.loads(
            stdout.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return invalid
    if not _valid_native_result(document):
        return invalid
    status = document["status"]
    if status == "running" or document["exit_code"] != process_exit_code:
        return invalid
    return {
        "status": status,
        "reason": f"native.{status}",
        "counts": _unknown_counts(),
    }
