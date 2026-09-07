#!/usr/bin/env python3
"""Linux-only synthetic experiment; does not run any source-project command."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time


PYTHON_GROUP_FIXTURE = r'''
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ready_path = Path(sys.argv[1])
child_ready_path = Path(sys.argv[2])
child_pid_path = Path(sys.argv[3])

signal.signal(signal.SIGTERM, signal.SIG_IGN)
grandchild_code = (
    "import os, pathlib, signal, sys, time; "
    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
    "time.sleep(60)"
)
grandchild = subprocess.Popen(
    [sys.executable, "-c", grandchild_code, str(child_ready_path)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
)
child_pid_path.write_text(str(grandchild.pid), encoding="utf-8")
deadline = time.monotonic() + 5
while not child_ready_path.exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if not child_ready_path.exists():
    raise SystemExit("grandchild did not signal ready")
ready_path.write_text(
    json.dumps({"pid": os.getpid(), "child_pid": grandchild.pid}),
    encoding="utf-8",
)
while True:
    time.sleep(1)
'''


NODE_GROUP_FIXTURE = r'''
const fs = require("fs");
const childProcess = require("child_process");

const readyPath = process.argv[2];
const childReadyPath = process.argv[3];
const childPidPath = process.argv[4];
process.on("SIGTERM", () => {});
const grandchildCode = [
  "const fs = require('fs');",
  "process.on('SIGTERM', () => {});",
  "fs.writeFileSync(process.argv[1], String(process.pid));",
  "setInterval(() => {}, 1000);",
].join("");
const grandchild = childProcess.spawn(
  process.execPath,
  ["-e", grandchildCode, childReadyPath],
  {stdio: "ignore"},
);
fs.writeFileSync(childPidPath, String(grandchild.pid));
const deadline = Date.now() + 5000;
const waitForReady = () => {
  if (fs.existsSync(childReadyPath)) {
    fs.writeFileSync(readyPath, JSON.stringify({
      pid: process.pid,
      child_pid: grandchild.pid,
    }));
    setInterval(() => {}, 1000);
    return;
  }
  if (Date.now() >= deadline) {
    process.exit(2);
    return;
  }
  setTimeout(waitForReady, 20);
};
waitForReady();
'''


def wait_ready(path, process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            return json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            if process.poll() is not None:
                raise RuntimeError("fixture exited before ready")
            time.sleep(0.02)
    raise TimeoutError("fixture ready handshake")


def reap_adopted():
    # Probe runs as its own process: only our synthetic descendants are adopted.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            time.sleep(0.02)
    raise RuntimeError("unreaped fixture descendants")


def candidate(name, executable, root):
    marker = root / (name + "-marker")
    literal = f"含空格 中文 $(touch {marker}) ; &"
    code = ("import json,sys; print(json.dumps(sys.argv[1:],ensure_ascii=False))"
            if name == "python" else
            "process.stdout.write(JSON.stringify(process.argv.slice(1)))")
    completed = subprocess.run(
        [executable, "-c" if name == "python" else "-e", code, literal],
        capture_output=True, text=True, check=True, timeout=5, shell=False)
    if json.loads(completed.stdout) != [literal] or marker.exists():
        raise RuntimeError("literal argv mismatch")
    ready = root / (name + "-ready.json")
    child_ready = root / (name + "-child-ready")
    fixture = root / (name + (".py" if name == "python" else ".js"))
    fixture.write_text(PYTHON_GROUP_FIXTURE if name == "python" else NODE_GROUP_FIXTURE)
    process = subprocess.Popen(
        [executable, str(fixture), str(ready), str(child_ready), str(root / (name + "-pid"))],
        cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        payload = wait_ready(ready, process)
        if payload["pid"] != process.pid or os.getpgid(process.pid) != process.pid:
            raise RuntimeError("fixture group identity mismatch")
        if os.getpgid(payload["child_pid"]) != process.pid:
            raise RuntimeError("fixture child not in group")
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise RuntimeError("fixture did not exercise kill fallback")
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)
        reap_adopted()
    if any(Path(f"/proc/{pid}").exists() for pid in payload.values()):
        raise RuntimeError("fixture process remains, including zombie")
    return {"status": "passed", "literal_argv": True, "ready_handshake": True,
            "sigterm_timeout": True, "sigkill_fallback": True,
            "no_leftover_processes": True}


def main():
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        print(json.dumps({"overall_status": "blocked", "reason": "requires Python 3.12/Linux"}))
        return 1
    # Linux PR_SET_CHILD_SUBREAPER: reap grandchildren even when the parent is killed.
    # This setting lasts only for this standalone probe process.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        print(json.dumps({"overall_status": "blocked", "reason": "subreaper unavailable"}))
        return 1
    summary = {"probe_version": "0.1.0", "python": platform.python_version(),
               "platform": platform.platform(), "node": None, "checks": {},
               "source_project_commands": False, "speed_benchmark": False}
    try:
        with tempfile.TemporaryDirectory(prefix="testpilot-probe-") as tmp:
            root = Path(tmp)
            node = shutil.which("node")
            summary["checks"]["python"] = candidate("python", sys.executable, root)
            if node:
                summary["node"] = subprocess.check_output([node, "--version"], text=True, timeout=5).strip()
                summary["checks"]["node"] = candidate("node", node, root)
            else:
                summary["checks"]["node"] = {"status": "not_available"}
            document = root / "知识库" / "示例 文档.md"
            document.parent.mkdir()
            content = "# 故障记录\n\n日志路径：中文/服务\n\n字面文本：$(touch 不应执行)\n"
            document.write_text(content, encoding="utf-8")
            record = {"path": str(document.relative_to(root)), "content": document.read_text(),
                      "sha256": hashlib.sha256(document.read_bytes()).hexdigest()}
            if json.loads(json.dumps(record, ensure_ascii=False)) != record or record["content"] != content:
                raise RuntimeError("Markdown roundtrip mismatch")
            summary["checks"]["markdown"] = {"status": "passed", "sha256": record["sha256"]}
        summary.update(overall_status="passed", recommendation="python3.12-linux")
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        summary.update(overall_status="failed", error=type(error).__name__)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
