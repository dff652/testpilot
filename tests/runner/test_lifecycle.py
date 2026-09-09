"""Real process, shared-resource, and recovery acceptance using owned fixtures."""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

from testpilot.contracts import validate
from testpilot.runner.process import process_identity
from testpilot.storage import MAX_ARTIFACT_BYTES
from tests.runner import test_cli

COUNTS = {"discovered": 2, "executed": 2, "passed": 2, "failed": 0, "skipped": 0}
PASS = "print(" + repr(json.dumps({"status": "passed", "counts": COUNTS})) + ")\n"
SLOW = '''import json,os,signal,subprocess,sys,time
from pathlib import Path
if sys.argv[1] == "fast":
    print(json.dumps({"status":"passed","counts":{"discovered":2,"executed":2,"passed":2,"failed":0,"skipped":0}}))
    raise SystemExit()
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable,"-c", "import os,signal,time;from pathlib import Path;os.setsid();signal.signal(signal.SIGTERM,signal.SIG_IGN);Path('child.ready').touch();time.sleep(60)"])
while not Path("child.ready").exists(): time.sleep(.01)
Path("ready.json").write_text(json.dumps({"parent":os.getpid(),"child":child.pid}))
time.sleep(60)
'''


def wait_until(check, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("fixture did not reach the expected state before deadline")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_cli.TestPilotCliTests("test_nonzero_process_is_not_passed")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.callers = []
        self.addCleanup(self.stop_callers)

    def stop_callers(self):
        for run_dir in (self.fixture.repo / ".testpilot" / "runs").glob("*/*"):
            if run_dir.is_dir():
                (run_dir / "cancel.request").touch()
        for caller in self.callers:
            if caller.poll() is None:
                caller.terminate()
            try:
                caller.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                caller.kill()
                caller.communicate(timeout=5)

    def configure(self, source, timeout=5):
        f = self.fixture
        (f.repo / "scripts" / "fixture.py").write_text(source)
        f.git(["add", "."])
        f.git(["commit", "-qm", "lifecycle fixture"])
        path = f.action()
        action = json.loads(path.read_text())
        action["policy"]["timeout_seconds"] = timeout
        path.write_text(json.dumps(action))
        f.register(path)

    def start(self, run_id="run.lifecycle"):
        f = self.fixture
        caller = subprocess.Popen(
            [sys.executable, str(test_cli.CLI), "run", "--registry", str(f.registry),
             "--checkout-id", "fixture-main", "--action-id", "test.synthetic", "--run-id", run_id],
            env=f.environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.callers.append(caller)
        ready = wait_until(lambda: (f.repo / "ready.json").exists())
        self.assertTrue(ready)
        run_dir = wait_until(lambda: next((f.repo / ".testpilot" / "runs" / run_id).glob("attempt.*"), None))
        wait_until(lambda: (run_dir / "supervisor.json").exists())
        return caller, run_dir, json.loads((f.repo / "ready.json").read_text())

    def assert_no_pids(self, pids):
        for pid in pids.values():
            self.assertFalse(Path(f"/proc/{pid}").exists(), f"fixture PID {pid} was not reaped")

    def control(self, name, run_dir):
        return self.fixture.cli(name, "--registry", self.fixture.registry,
                                "--checkout-id", "fixture-main", "--run-id", run_dir.parent.name,
                                "--attempt-id", run_dir.name)

    def test_timeout_reaps_term_resistant_and_escaped_descendants(self):
        self.configure(SLOW, timeout=1)
        caller, run_dir, pids = self.start()
        stdout, stderr = caller.communicate(timeout=10)
        self.assertEqual(caller.returncode, 124, stderr)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "timed_out")
        self.assertFalse(validate("result", result))
        capture = json.loads((run_dir / "capture.json").read_text())
        self.assertTrue(capture["sigkill_used"])
        self.assertTrue(capture["no_leftover_processes"])
        self.assert_no_pids(pids)

    def test_cancel_and_git_worktree_lock(self):
        self.configure(SLOW, timeout=20)
        f = self.fixture
        other = f.root / "other-worktree"
        f.git(["worktree", "add", "-q", "-b", "other", str(other), "HEAD"])
        action = f.action("test.fast", mode="fast")
        registration = f.cli("register", "--registry", f.registry, "--checkout-id", "fixture-other",
                             "--project-id", "fixture", "--checkout", other, "--action", action,
                             "--tool", f"python3={sys.executable}")
        self.assertEqual(registration.returncode, 0, registration.stdout)
        caller, run_dir, pids = self.start()
        args = ("run", "--registry", f.registry, "--checkout-id", "fixture-other", "--action-id", "test.fast")
        blocked = f.result(f.cli(*args))
        self.assertEqual((blocked["status"], blocked["reason"]), ("blocked", "lock.busy"))
        self.assertTrue(json.loads(self.control("cancel", run_dir).stdout)["cancel_requested"])
        stdout, _ = caller.communicate(timeout=10)
        self.assertEqual(json.loads(stdout)["status"], "cancelled")
        self.assert_no_pids(pids)
        self.assertEqual(f.result(f.cli(*args))["status"], "passed")

    def enable_adoption(self):
        libc = ctypes.CDLL(None)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        self.addCleanup(lambda: libc.prctl(36, previous.value, 0, 0, 0))

    def reap(self, pid):
        def reaped():
            try:
                return os.waitpid(pid, os.WNOHANG)[0] == pid
            except ChildProcessError:
                return not Path(f"/proc/{pid}").exists()
        wait_until(reaped)

    def test_caller_sigkill_supervisor_retains_lock_and_cleans_up(self):
        self.enable_adoption()
        self.configure(SLOW, timeout=20)
        caller, run_dir, pids = self.start()
        supervisor = json.loads((run_dir / "supervisor.json").read_text())["pid"]
        caller.kill()
        caller.communicate(timeout=5)
        result = wait_until(lambda: self.terminal(run_dir))
        self.assertEqual((result["status"], result["reason"]), ("runner_error", "runner.owner_lost"))
        self.reap(supervisor)
        self.assert_no_pids(pids)
        report = self.fixture.cli("recover", "--registry", self.fixture.registry, "--checkout-id", "fixture-main")
        self.assertEqual(json.loads(report.stdout)["status"], "idle")

    def terminal(self, run_dir):
        result = json.loads((run_dir / "result.json").read_text())
        return result if result["status"] not in ("running", "queued") else None

    def test_supervisor_loss_blocks_recovery_until_survivors_are_gone(self):
        self.enable_adoption()
        self.configure(SLOW, timeout=20)
        caller, run_dir, pids = self.start()
        supervisor = json.loads((run_dir / "supervisor.json").read_text())["pid"]
        try:
            os.kill(supervisor, signal.SIGKILL)
            stdout, _ = caller.communicate(timeout=10)
            result = json.loads(stdout)
            self.assertEqual((result["status"], result["reason"]), ("runner_error", "recovery.live_children"))
            report = self.fixture.cli("recover", "--registry", self.fixture.registry, "--checkout-id", "fixture-main")
            self.assertEqual(json.loads(report.stdout)["status"], "blocked")
        finally:
            for pid in pids.values():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pid in pids.values():
                self.reap(pid)
        report = self.fixture.cli("recover", "--registry", self.fixture.registry, "--checkout-id", "fixture-main")
        payload = json.loads(report.stdout)
        self.assertEqual(payload["status"], "recovered")
        self.assertEqual(payload["results"][0]["status"], "runner_error")
        self.assert_no_pids(pids)

    def test_output_limit_preserves_bounded_raw_evidence(self):
        self.configure("import os\nos.write(1, b'x' * (12 * 1024 * 1024))\n", timeout=10)
        result = self.fixture.result(self.fixture.run_action())
        self.assertEqual((result["status"], result["reason"]), ("inconclusive", "output.truncated"))
        run_dir = self.fixture.repo / ".testpilot" / "runs" / result["run_id"] / result["attempt_id"]
        for artifact in result["artifacts"]:
            path = run_dir / artifact["path"]
            self.assertLessEqual(path.stat().st_size, MAX_ARTIFACT_BYTES)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(run_dir.stat().st_mode & 0o777, 0o700)

    def test_recovery_does_not_cross_checkout_and_handles_queued_state(self):
        from testpilot.registry import load_checkout, fingerprint
        from testpilot.runner.results import initial_result
        from testpilot.runner.service import attempt_directory, lock_resource, save_result
        from testpilot.storage import private_directory, atomic_json
        f = self.fixture
        self.configure(PASS)
        entry = load_checkout(f.registry, "fixture-main")
        job = {"entry": entry, "pinned": entry["actions"]["test.synthetic"],
               "checkout_id": "fixture-main", "action_id": "test.synthetic",
               "run_id": "run.interrupted", "attempt_id": "attempt.queued",
               "provenance": fingerprint(f.repo)}
        run_dir = private_directory(attempt_directory(entry, job["run_id"], job["attempt_id"]))
        result = initial_result(job)
        result.update(status="queued", started_at=None, reason="runner.queued")
        atomic_json(run_dir / "job.json", job)
        save_result(run_dir, result)
        descriptor, state = lock_resource(entry)
        atomic_json(state / "active.json", {"entry": entry, "run_id": job["run_id"], "attempt_id": job["attempt_id"]})
        os.close(descriptor)
        other = f.root / "foreign-worktree"
        f.git(["worktree", "add", "-q", "-b", "foreign", str(other), "HEAD"])
        action_path = f.action()
        action = json.loads(action_path.read_text())
        action["project_id"] = "foreign-project"
        action_path.write_text(json.dumps(action))
        registry = f.root / "foreign-registry.json"
        registered = f.cli("register", "--registry", registry, "--checkout-id", "foreign-checkout",
                           "--project-id", "foreign-project", "--checkout", other,
                           "--action", action_path, "--tool", f"python3={sys.executable}")
        self.assertEqual(registered.returncode, 0, registered.stdout)
        foreign = f.cli("recover", "--registry", registry, "--checkout-id", "foreign-checkout")
        self.assertEqual(foreign.returncode, 2)
        self.assertEqual(json.loads(foreign.stdout), {"status": "blocked", "reason": "recovery.other_checkout_active", "results": []})
        self.assertTrue((state / "active.json").exists())
        self.assertEqual(json.loads((run_dir / "result.json").read_text())["status"], "queued")
        own = f.cli("recover", "--registry", f.registry, "--checkout-id", "fixture-main")
        recovered = json.loads(own.stdout)
        self.assertEqual(own.returncode, 0, own.stdout)
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(recovered["results"][0]["reason"], "runner.interrupted")
        self.assertIsNone(recovered["results"][0]["started_at"])
        self.assertFalse((state / "active.json").exists())

    def test_redaction_expansion_is_also_marked_truncated(self):
        self.configure("import sys\n" + PASS + "sys.stderr.write('token=x\\n' * 700000)\n", timeout=10)
        result = self.fixture.result(self.fixture.run_action())
        self.assertEqual((result["status"], result["reason"]), ("inconclusive", "output.truncated"))
        run_dir = self.fixture.repo / ".testpilot" / "runs" / result["run_id"] / result["attempt_id"]
        facts = json.loads((run_dir / "capture.json").read_text())
        self.assertLess(facts["bytes_seen"]["stderr"], MAX_ARTIFACT_BYTES)
        self.assertIn("stderr.log", facts["truncated"])
        self.assertEqual((run_dir / "stderr.log").stat().st_size, MAX_ARTIFACT_BYTES)

    def test_all_skipped_and_nonzero_success_report_are_not_passed(self):
        f = self.fixture
        skipped = {"status": "passed", "counts": {"discovered": 2, "executed": 0, "passed": 0, "failed": 0, "skipped": 2}}
        self.configure("print(" + repr(json.dumps(skipped)) + ")\n")
        self.assertEqual(f.result(f.run_action())["status"], "inconclusive")
        (f.repo / "scripts/fixture.py").write_text(PASS + "raise SystemExit(7)\n")
        f.git(["add", "scripts/fixture.py"])
        f.git(["commit", "-qm", "nonzero fixture"])
        path = f.action(action_id="test.nonzero")
        f.register(path)
        result = f.result(f.run_action("test.nonzero"))
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 7))

    def test_non_utf8_caller_can_register_chinese_checkout(self):
        f = self.fixture
        renamed = f.root / "中文 checkout"
        f.repo.rename(renamed)
        f.repo = renamed
        environment = f.environment()
        environment.update(LC_ALL="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        f.environment = lambda: environment
        parent_mode = f.root.stat().st_mode & 0o777
        self.configure(PASS)
        result = f.result(f.run_action())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(f.root.stat().st_mode & 0o777, parent_mode)

    def test_ambiguous_fixture_json_cannot_be_passed(self):
        from testpilot.runner.results import fixture_result
        for raw in (b'{"status":"failed","status":"passed","counts":{}}',
                    b'{"status":"passed","counts":{"executed":NaN}}'):
            with self.subTest(raw=raw):
                self.assertEqual(fixture_result(raw)["status"], "inconclusive")

    def test_clean_environment_and_redacted_derivative(self):
        f = self.fixture
        environment = f.environment()
        environment["TESTPILOT_PARENT_SECRET"] = "synthetic-parent-only"
        f.environment = lambda: environment
        secret = "synthetic-" + "fixture-value"
        source = ("import json,os\nfrom pathlib import Path\n"
                  "Path('environment.json').write_text(json.dumps({'inherited': 'TESTPILOT_PARENT_SECRET' in os.environ,'home':os.environ['HOME']}))\n"
                  + "print(" + repr("token=" + secret) + ")\n")
        self.configure(source)
        result = f.result(f.run_action())
        self.assertNotEqual(result["status"], "passed")
        run_dir = f.repo / ".testpilot" / "runs" / result["run_id"] / result["attempt_id"]
        observed = json.loads((f.repo / "environment.json").read_text())
        self.assertFalse(observed["inherited"])
        self.assertEqual(observed["home"], str(run_dir / "home"))
        self.assertIn(secret, (run_dir / "stdout.raw").read_text())
        self.assertNotIn(secret, (run_dir / "report.json").read_text())
        self.assertIn("[REDACTED]", (run_dir / "report.json").read_text())
