"""Result mapping keeps process exit, report parsing, and evidence distinct."""
from datetime import datetime, timezone
import platform
import re

from ..contracts import validate
from ..storage import MAX_ARTIFACT_BYTES, atomic_json, decode_json, digest, write_private

COUNT_KEYS = ("discovered", "executed", "passed", "failed", "skipped")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def unknown_counts():
    return dict.fromkeys(COUNT_KEYS)


def initial_result(job):
    provenance = dict(job["provenance"])
    provenance.update(action_sha256=job["pinned"]["action_sha256"],
                      environment=f"Python {platform.python_version()}; Linux; clean environment; network policy none (not OS-isolated)")
    return {"schema_version": "0.1.0", "project_id": job["entry"]["project_id"],
            "checkout_id": job["checkout_id"], "action_id": job["action_id"],
            "run_id": job["run_id"], "attempt_id": job["attempt_id"],
            "kind": job["pinned"]["action"]["kind"], "status": "running",
            "exit_code": None, "signal": None, "started_at": now(), "ended_at": None,
            "duration_ms": None, "reason": "process.running", "counts": unknown_counts(),
            "artifacts": [], "missing_artifacts": [], "provenance": provenance}


def finish(result, status, reason, *, returncode=None):
    result.update(status=status, reason=reason, ended_at=now())
    result["duration_ms"] = (max(0, int((datetime.fromisoformat(result["ended_at"]) -
                                       datetime.fromisoformat(result["started_at"])).total_seconds() * 1000))
                             if result["started_at"] is not None else 0)
    if returncode is not None:
        result["exit_code"] = returncode if returncode >= 0 else None
        result["signal"] = -returncode if returncode < 0 else None
    return result


def redact(data):
    text = data.decode("utf-8", "replace")
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                  "[REDACTED_PRIVATE_KEY]", text, flags=re.DOTALL)
    text = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer|basic)\s+)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)([\"']?(?:api[_-]?key|token|password|secret)[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+",
                  r"\1[REDACTED]", text)
    return text.encode("utf-8")


def artifact(run_dir, name, redacted=True):
    data = (run_dir / name).read_bytes()
    return {"path": name, "sha256": digest(data), "media_type": "application/json" if name.endswith(".json") else "text/plain",
            "size_bytes": len(data), "redacted": redacted}


def fixture_result(stdout):
    try:
        data = decode_json(stdout)
    except (ValueError, UnicodeError):
        return {"status": "inconclusive", "reason": "fixture.invalid_report", "counts": unknown_counts()}
    if (not isinstance(data, dict) or set(data) != {"status", "counts"}
            or data["status"] not in ("passed", "failed", "inconclusive")):
        return {"status": "inconclusive", "reason": "fixture.invalid_report", "counts": unknown_counts()}
    return {"status": data["status"], "reason": "fixture.report", "counts": data["counts"]}


def observed_result(job, run_dir, result, facts):
    stdout = (run_dir / "stdout.raw").read_bytes()
    stderr = (run_dir / "stderr.raw").read_bytes()
    # RunResult 0.1.0 permits sanitized artifacts only; raw bytes stay private.
    atomic_json(run_dir / "raw-manifest.json",
                {"artifacts": [artifact(run_dir, name, False)
                               for name in ("stdout.raw", "stderr.raw")]})
    parser = job["pinned"]["action"]["acceptance"]["parser"]
    report = "report.json" if parser == "fixture-json" else "native-output.log"
    if stdout:
        cleaned = redact(stdout)
        if len(cleaned) > MAX_ARTIFACT_BYTES:
            facts["truncated"].append(report)
        write_private(run_dir / report, cleaned[:MAX_ARTIFACT_BYTES])
        result["artifacts"].append(artifact(run_dir, report, True))
    else:
        result["missing_artifacts"] = [report]
    cleaned_stderr = redact(stderr)
    if len(cleaned_stderr) > MAX_ARTIFACT_BYTES:
        facts["truncated"].append("stderr.log")
    write_private(run_dir / "stderr.log", cleaned_stderr[:MAX_ARTIFACT_BYTES])
    result["artifacts"].append(artifact(run_dir, "stderr.log", True))
    if facts["truncated"] and facts["reason"] is None:
        facts["reason"] = "output.truncated"
    atomic_json(run_dir / "capture.json", facts)
    for name in ("raw-manifest.json", "capture.json"):
        result["artifacts"].append(artifact(run_dir, name))
    reason = facts["reason"]
    if reason:
        status = {"process.cancelled": "cancelled", "process.timed_out": "timed_out",
                  "output.truncated": "inconclusive"}.get(reason, "runner_error")
        return finish(result, status, reason, returncode=facts["returncode"])
    if parser == "fixture-json":
        mapped = fixture_result(stdout)
    else:
        from ..adapters.agent_mail import parse_result
        mapped = parse_result(stdout, facts["returncode"])
    result.update(mapped)
    if facts["returncode"] != 0 and result["status"] in {"passed", "inconclusive"}:
        result.update(status="failed", reason="process.nonzero_exit")
    if not stdout and facts["returncode"] == 0:
        result.update(status="inconclusive", reason="report.missing")
    finish(result, result["status"], result["reason"], returncode=facts["returncode"])
    if validate("result", result):
        result.update(status="inconclusive", reason="report.invalid_result", counts=unknown_counts())
    return result
