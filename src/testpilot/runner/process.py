"""A dedicated Linux supervisor owns and reaps an action's process family."""
import ctypes
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from ..storage import MAX_ARTIFACT_BYTES, PilotError, atomic_json


def process_identity(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return {"pid": pid, "start": int(fields[19]), "parent": int(fields[1]),
                "group": int(fields[2]), "state": fields[0]}
    except (OSError, ValueError, IndexError):
        return None


def alive(identity):
    current = process_identity(identity["pid"]) if identity else None
    return bool(current and current["start"] == identity["start"] and current["state"] != "Z")


def descendants():
    snapshot = [process_identity(int(path.name)) for path in Path("/proc").iterdir() if path.name.isdigit()]
    family = {os.getpid()}
    found = {}
    while True:
        additions = [item for item in snapshot if item and item["parent"] in family and item["pid"] not in family]
        if not additions:
            return list(found.values())
        for item in additions:
            family.add(item["pid"])
            found[item["pid"]] = item


def signal_family(signum):
    # pidfds bind signals to a process instance rather than a potentially reused PID.
    for item in descendants():
        try:
            descriptor = os.pidfd_open(item["pid"])
        except ProcessLookupError:
            continue
        try:
            if alive(item):
                signal.pidfd_send_signal(descriptor, signum)
        except ProcessLookupError:
            pass
        finally:
            os.close(descriptor)


def reap_children():
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def execute(job, run_dir):
    """Capture bounded streams; return observed process facts, never a PASS verdict."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise PilotError("process.subreaper_unavailable")
    cancelled = False

    def on_signal(_number, _frame):
        nonlocal cancelled
        cancelled = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(run_dir / "home"),
                   "TMPDIR": str(run_dir / "tmp"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1",
                   "TESTPILOT_ATTEMPT": job["attempt_id"]}
    for directory in ("home", "tmp"):
        (run_dir / directory).mkdir(mode=0o700)
    started = time.monotonic()
    process = subprocess.Popen(job["argv"], cwd=job["cwd"], env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    streams = {}
    sizes = {"stdout": 0, "stderr": 0}
    truncated = []
    stop_reason = None
    term_at = None
    killed = False
    try:
        atomic_json(run_dir / "process.json", process_identity(process.pid))
        for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
            descriptor = os.open(run_dir / f"{name}.raw", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            streams[name] = os.fdopen(descriptor, "wb")
        while True:
            now = time.monotonic()
            if stop_reason is None:
                if not alive(job["owner"]):
                    stop_reason = "runner.owner_lost"
                elif cancelled or (run_dir / "cancel.request").exists():
                    stop_reason = "process.cancelled"
                elif now - started >= job["timeout"]:
                    stop_reason = "process.timed_out"
                elif truncated:
                    stop_reason = "output.truncated"
                elif process.poll() is not None and descendants():
                    stop_reason = "process.descendants_leftover"
            if stop_reason and term_at is None:
                signal_family(signal.SIGTERM)
                term_at = now
            if term_at is not None and now - term_at >= 0.25:
                signal_family(signal.SIGKILL)
                killed = True
            for key, _ in selector.select(timeout=0.02):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                name = key.data
                keep = max(0, MAX_ARTIFACT_BYTES - sizes[name])
                streams[name].write(chunk[:keep])
                sizes[name] += len(chunk)
                if sizes[name] > MAX_ARTIFACT_BYTES and name not in truncated:
                    truncated.append(name)
            if process.poll() is not None:
                reap_children()
                if not selector.get_map() and not descendants():
                    break
            if term_at is not None and now - term_at > 4:
                raise PilotError("process.cleanup_incomplete")
        code = process.wait()
    finally:
        signal_family(signal.SIGKILL)
        process.wait(timeout=5)
        deadline = time.monotonic() + 3
        while descendants() and time.monotonic() < deadline:
            signal_family(signal.SIGKILL)
            reap_children()
            time.sleep(0.01)
        remaining = descendants()
        selector.close()
        for pipe in (process.stdout, process.stderr):
            pipe.close()
        for stream in streams.values():
            stream.close()
        if remaining:
            raise PilotError("process.cleanup_incomplete")
    facts = {"returncode": code, "reason": stop_reason, "bytes_seen": sizes,
             "truncated": truncated, "sigkill_used": killed, "no_leftover_processes": True}
    atomic_json(run_dir / "capture.json", facts)
    return facts
