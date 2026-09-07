#!/usr/bin/env python3
"""Offline structural and cross-field checks; never executes declared actions."""
import argparse
from datetime import datetime
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("action", "result", "knowledge")


def _count_errors(counts, require_no_failures=False):
    """Check whether known counts have a nonnegative integer completion.

    The execution count must lie in the interval implied by known passed,
    failed, discovered, and skipped values.  A passed result additionally
    treats an unknown failed count as zero, so it cannot hide an inferred
    failure while preserving genuinely all-unknown check results.
    """
    discovered = counts["discovered"]
    executed = counts["executed"]
    passed = counts["passed"]
    failed = counts["failed"]
    skipped = counts["skipped"]
    if require_no_failures and failed is None:
        failed = 0
    lower = (passed if passed is not None else 0) + (failed if failed is not None else 0)
    upper = None
    if passed is not None and failed is not None:
        upper = lower
    if executed is not None:
        lower = max(lower, executed)
        upper = executed if upper is None else min(upper, executed)
    if discovered is not None:
        upper = discovered if upper is None else min(upper, discovered)
    if discovered is not None and skipped is not None:
        if discovered < skipped:
            return ["counts:inconsistent"]
        exact_from_discovered = discovered - skipped
        lower = max(lower, exact_from_discovered)
        upper = exact_from_discovered if upper is None else min(upper, exact_from_discovered)
    if upper is not None and lower > upper:
        return ["counts:inconsistent"]
    return []


def validate(kind, data):
    schema = json.loads((ROOT / "contracts" / f"{kind}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    # Return locations, not values: malformed inputs could contain secrets.
    errors = [f"schema:{'/'.join(map(str, e.absolute_path))}:{e.validator}"
              for e in validator.iter_errors(data)]
    if errors:
        return errors
    if kind == "action":
        executable = data["runner"]["executable"]
        arguments = data["runner"]["argv"]
        interpreter = (executable in {"sh", "bash", "dash", "zsh", "ksh", "node"}
                       or executable.startswith("python"))
        if interpreter and (not arguments or arguments[0]["type"] != "path"):
            errors.append("runner:typed_entry_path_required")
        # Only the first argument selects the interpreter entry point.  Later
        # literals belong to the script and may legitimately resemble options
        # such as ``-c`` or ``--eval``.
        if interpreter and arguments and arguments[0]["type"] == "path":
            entry = arguments[0]["value"]
            if entry.startswith("-"):
                errors.append("runner:entry_path_is_interpreter_option")
    times = {}
    for name in ("started_at", "ended_at", "verified_at", "updated_at"):
        if data.get(name) is not None:
            try:
                times[name] = datetime.fromisoformat(data[name])
            except ValueError:
                errors.append(f"invalid_datetime:{name}")
    if kind == "result":
        paths = [a["path"] for a in data["artifacts"]]
        if len(paths) != len(set(paths)):
            errors.append("artifacts:duplicate_path")
        c = data["counts"]
        errors.extend(_count_errors(c, require_no_failures=data["status"] == "passed"))
        if "started_at" in times and "ended_at" in times:
            if times["ended_at"] < times["started_at"]:
                errors.append("time:reversed")
        if data["status"] in ("passed", "failed", "cancelled", "timed_out"):
            if data["duration_ms"] is None:
                errors.append("time:missing_duration")
    if kind == "knowledge":
        if data["source"]["project_id"] != data["project_id"]:
            errors.append("source:project_mismatch")
        if data["source"]["line_end"] < data["source"]["line_start"]:
            errors.append("source:reversed_lines")
        for evidence in data["evidence"]:
            if evidence["project_id"] != data["project_id"]:
                errors.append("evidence:project_mismatch")
        replacement = data["superseded_by"]
        if replacement is not None:
            if replacement["project_id"] != data["project_id"]:
                errors.append("replacement:project_mismatch")
            if replacement["knowledge_id"] == data["knowledge_id"]:
                errors.append("knowledge:self_superseded")
        if "verified_at" in times and "updated_at" in times:
            if times["verified_at"] > times["updated_at"]:
                errors.append("time:verification_after_update")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        errors = validate(args.kind, json.loads(args.file.read_text()))
    except (OSError, ValueError):
        errors = ["input:unreadable_or_invalid_json"]
    print(json.dumps({"valid": not errors, "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
