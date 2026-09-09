"""Local run lifecycle; a separate supervisor retains locks if the caller dies."""
import fcntl
import os
from pathlib import Path
import signal
import subprocess
import sys
import traceback
import uuid

from ..contracts import validate
from ..registry import checkout_identity, command, fingerprint, load_checkout
from ..storage import (PilotError, atomic_json, identifier, private_directory,
                       read_json)
from .process import alive, execute, process_identity
from .results import finish, initial_result, observed_result

CLI = Path(__file__).resolve().parents[3] / "scripts" / "testpilot.py"


def lock_resource(entry):
    state = private_directory(Path(entry["git_common_dir"]) / "testpilot")
    descriptor = os.open(state / "runner.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise PilotError("lock.busy") from None
    return descriptor, state


def save_result(run_dir, result):
    if validate("result", result):
        raise PilotError("runner.invalid_result")
    atomic_json(run_dir / "result.json", result)


def attempt_directory(entry, run_id, attempt_id):
    identifier(run_id)
    identifier(attempt_id)
    path = Path(entry["root"]) / ".testpilot" / "runs" / run_id / attempt_id
    # No symlinked evidence directories, including links staying inside the checkout.
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise PilotError("storage.symlink")
    return path


def read_result(entry, run_id, attempt_id):
    result = read_json(attempt_directory(entry, run_id, attempt_id) / "result.json")
    if (validate("result", result) or result["project_id"] != entry["project_id"]
            or result["checkout_id"] != entry["checkout_id"]
            or result["run_id"] != run_id or result["attempt_id"] != attempt_id):
        raise PilotError("identity.result_mismatch")
    return result


def lingering(job, run_dir):
    """Fail closed on identified survivors after an abnormal supervisor loss."""
    identity_path = run_dir / "process.json"
    child = read_json(identity_path) if identity_path.exists() else None
    if child and alive(child):
        return True
    marker = f'TESTPILOT_ATTEMPT={job["attempt_id"]}'.encode()
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        current = process_identity(int(path.name))
        if child and current and current["group"] == child["group"]:
            return True  # includes zombies; never call them cleaned up
        try:
            with (path / "environ").open("rb") as stream:
                if marker in stream.read(1024 * 1024).split(b"\0"):
                    return True
        except (OSError, PermissionError):
            continue
    return False


def recover_active(entry, state):
    active_path = state / "active.json"
    if not active_path.exists():
        return {"status": "idle", "results": []}
    active = read_json(active_path)
    old_entry = active["entry"]
    if any(old_entry.get(key) != entry.get(key) for key in ("checkout_id", "project_id", "root")):
        return {"status": "blocked", "reason": "recovery.other_checkout_active", "results": []}
    _, common = checkout_identity(old_entry["root"])
    if str(common) != entry["git_common_dir"]:
        raise PilotError("identity.recovery_mismatch")
    run_dir = attempt_directory(old_entry, active["run_id"], active["attempt_id"])
    job = read_json(run_dir / "job.json")
    if (job["entry"] != old_entry or job["run_id"] != active["run_id"]
            or job["attempt_id"] != active["attempt_id"]):
        raise PilotError("identity.recovery_job_mismatch")
    result = read_result(old_entry, active["run_id"], active["attempt_id"])
    if lingering(job, run_dir):
        # Do not signal processes based on stale PIDs or manufacture cleanup evidence.
        if result["status"] in {"queued", "running"}:
            finish(result, "runner_error", "recovery.live_children")
            save_result(run_dir, result)
        return {"status": "blocked", "reason": "recovery.live_children", "results": [result]}
    if result["status"] in {"queued", "running"}:
        finish(result, "runner_error", "runner.interrupted")
        save_result(run_dir, result)
    active_path.unlink()
    return {"status": "recovered", "results": [result]}


def recover(registry, checkout_id):
    entry = load_checkout(registry, checkout_id)
    try:
        descriptor, state = lock_resource(entry)
    except PilotError as error:
        if str(error) == "lock.busy":
            return {"status": "busy", "reason": "lock.busy", "results": []}
        raise
    try:
        return recover_active(entry, state)
    finally:
        os.close(descriptor)


def run(registry, checkout_id, action_id, *, run_id=None):
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        raise PilotError("platform.python312_linux_required")
    entry = load_checkout(registry, checkout_id)
    identifier(action_id)
    try:
        pinned = entry["actions"][action_id]
    except KeyError:
        raise PilotError("action.not_registered") from None
    run_id = identifier(run_id) if run_id else "run." + uuid.uuid4().hex
    attempt_id = "attempt." + uuid.uuid4().hex
    run_dir = attempt_directory(entry, run_id, attempt_id)
    private_directory(run_dir)
    job = {"entry": entry, "pinned": pinned, "checkout_id": checkout_id, "action_id": action_id,
           "run_id": run_id, "attempt_id": attempt_id, "owner": process_identity(os.getpid()),
           "provenance": fingerprint(entry["root"]), "timeout": pinned["action"]["policy"]["timeout_seconds"]}
    result = initial_result(job)
    try:
        descriptor, state = lock_resource(entry)
    except PilotError as error:
        finish(result, "blocked", str(error))
        save_result(run_dir, result)
        return result
    try:
        recovered = recover_active(entry, state)
        if recovered["status"] == "blocked":
            raise PilotError(recovered["reason"])
        job["argv"], job["cwd"] = command(entry, pinned)
        # Snapshot after acquiring the shared lock and validating registered inputs.
        job["provenance"] = fingerprint(entry["root"])
        result = initial_result(job)
        atomic_json(run_dir / "job.json", job)
        save_result(run_dir, result)
        atomic_json(state / "active.json", {"entry": entry, "run_id": run_id, "attempt_id": attempt_id})
        environment = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "PYTHONUTF8": "1"}
        log_fd = os.open(run_dir / "supervisor.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(log_fd, "wb") as log:
            worker = subprocess.Popen([sys.executable, "-I", "-X", "utf8", str(CLI), "_supervise",
                                       "--job", str(run_dir / "job.json"), "--lock-fd", str(descriptor)],
                                      pass_fds=(descriptor,), start_new_session=True,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=log, env=environment)
    except (PilotError, OSError) as error:
        reason = str(error) if isinstance(error, PilotError) else "runner.start_failed"
        finish(result, "blocked", reason)
        save_result(run_dir, result)
        os.close(descriptor)
        return result
    # The supervisor owns the same open file description; closing here does not unlock it.
    os.close(descriptor)
    previous = {}

    def cancel(_number, _frame):
        atomic_json(run_dir / "cancel.request", {"requested": True})

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, cancel)
    try:
        worker.wait()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    result = read_result(entry, run_id, attempt_id)
    if result["status"] in {"queued", "running"}:
        recover(registry, checkout_id)
        result = read_result(entry, run_id, attempt_id)
    return result


def supervise(job_path, descriptor):
    job_path = Path(job_path)
    job = read_json(job_path)
    run_dir = attempt_directory(job["entry"], job["run_id"], job["attempt_id"])
    if run_dir / "job.json" != job_path:
        raise PilotError("identity.job_mismatch")
    state = Path(job["entry"]["git_common_dir"]) / "testpilot"
    lock_stat = os.fstat(descriptor)
    path_stat = (state / "runner.lock").stat()
    if (lock_stat.st_dev, lock_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino):
        raise PilotError("lock.invalid_supervisor_descriptor")
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    active = read_json(state / "active.json")
    if (active["run_id"] != job["run_id"] or active["attempt_id"] != job["attempt_id"]
            or active["entry"] != job["entry"]):
        raise PilotError("identity.active_job_mismatch")
    result = read_result(job["entry"], job["run_id"], job["attempt_id"])
    atomic_json(run_dir / "supervisor.json", process_identity(os.getpid()))
    cleanup_ok = False
    try:
        argv, cwd = command(job["entry"], job["pinned"])
        if argv != job["argv"] or cwd != job["cwd"]:
            raise PilotError("identity.command_mismatch")
        if not alive(job["owner"]):
            finish(result, "runner_error", "runner.owner_lost")
            cleanup_ok = True
        else:
            facts = execute(job, run_dir)
            cleanup_ok = True
            result = observed_result(job, run_dir, result, facts)
    except Exception as error:
        atomic_json(run_dir / "supervisor-error.json", {"type": type(error).__name__,
                    "frames": [{"file": Path(frame.filename).name, "line": frame.lineno}
                               for frame in traceback.extract_tb(error.__traceback__)]})
        started_at = result["started_at"]
        result = initial_result(job)
        result["started_at"] = started_at
        finish(result, "runner_error", "runner.execution_error")
    finally:
        save_result(run_dir, result)
        if cleanup_ok:
            (state / "active.json").unlink(missing_ok=True)
        os.close(descriptor)
    return 0


def cancel_run(registry, checkout_id, run_id, attempt_id):
    entry = load_checkout(registry, checkout_id)
    result = read_result(entry, run_id, attempt_id)
    requested = result["status"] in {"queued", "running"}
    if requested:
        atomic_json(attempt_directory(entry, run_id, attempt_id) / "cancel.request", {"requested": True})
    return {"cancel_requested": requested}
