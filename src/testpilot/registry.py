"""Explicit checkout registration, executable pinning, and Git provenance."""
import fcntl
import os
from pathlib import Path
import stat
import subprocess

from .contracts import validate
from .storage import (PilotError, atomic_json, digest, identifier, inside,
                      json_bytes, private_directory, read_json)


def git(checkout, *arguments):
    # Fixed Git operations; disable per-repository fsmonitor hooks and prompting.
    environment = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                   "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(checkout), *arguments],
            env=environment, capture_output=True, timeout=30, check=True)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise PilotError("checkout.git_error") from None


def checkout_identity(checkout):
    root = Path(checkout).resolve(strict=True)
    top = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel").strip())).resolve()
    if root != top:
        raise PilotError("checkout.root_required")
    common = Path(os.fsdecode(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())).resolve()
    return root, common


def fingerprint(checkout):
    """Hash tracked and nonignored worktree content, excluding own evidence."""
    paths = sorted(set(git(checkout, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")) - {b""})
    entries = []
    for raw in paths:
        relative = os.fsdecode(raw)
        if relative == ".testpilot" or relative.startswith(".testpilot/"):
            continue
        path = Path(checkout) / relative
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                content = os.fsencode(os.readlink(path))
            elif stat.S_ISREG(mode):
                # Streaming avoids holding a whole large project file in memory.
                import hashlib
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        hasher.update(block)
                entries.append([relative, stat.S_IMODE(mode), hasher.hexdigest()])
                continue
            else:
                raise PilotError("checkout.unsupported_file")
        except FileNotFoundError:
            content, mode = b"missing", 0
        entries.append([relative, stat.S_IMODE(mode), digest(content)])
    return {
        "commit": git(checkout, "rev-parse", "HEAD").decode().strip(),
        "dirty": bool(git(checkout, "status", "--porcelain", "--untracked-files=normal", "--", ".", ":(exclude).testpilot")),
        "content_sha256": digest(json_bytes(entries)),
    }


def policy_check(action):
    if validate("action", action):
        raise PilotError("action.invalid_contract")
    if action["policy"]["network"] != "none" or action["policy"]["secrets"] != "forbidden":
        raise PilotError("policy.unsupported")
    if action["policy"]["locks"] != ["git-common-dir"]:
        raise PilotError("policy.unsupported_locks")
    pair = (action["adapter_id"], action["acceptance"]["parser"])
    if pair not in {("fixture", "fixture-json"), ("sop-result", "sop-result")}:
        raise PilotError("adapter.unsupported")
    if pair == ("sop-result", "sop-result") and (action["project_id"], action["action_id"], action["kind"]) != ("agent-mail", "versions.check", "check"):
        raise PilotError("adapter.action_not_allowed")
    expected = "report.json" if pair[1] == "fixture-json" else "native-output.log"
    if action["acceptance"]["required_artifacts"] != [expected]:
        raise PilotError("adapter.unsupported_artifacts")


def pin_action(checkout, action, tools):
    policy_check(action)
    executable = action["runner"]["executable"]
    if executable not in tools or not Path(tools[executable]).is_absolute():
        raise PilotError("tool.explicit_path_required")
    tool = Path(tools[executable]).resolve(strict=True)
    if not tool.is_file() or not os.access(tool, os.X_OK):
        raise PilotError("tool.not_executable")
    files = {}
    for relative in [action["source"]["path"], *(arg["value"] for arg in action["runner"]["argv"] if arg["type"] == "path")]:
        target = inside(checkout, relative)
        if target.is_file():
            files[relative] = digest(target.read_bytes())
        elif not target.is_dir():
            raise PilotError("path.invalid_type")
    source = action["source"]
    if files.get(source["path"]) != source["sha256"]:
        raise PilotError("source.hash_mismatch")
    original = git(checkout, "show", f'{source["commit"]}:{source["path"]}')
    if digest(original) != source["sha256"]:
        raise PilotError("source.commit_mismatch")
    cwd = inside(checkout, action["runner"]["cwd"])
    if not cwd.is_dir():
        raise PilotError("path.cwd_not_directory")
    if not action["runner"]["argv"] or action["runner"]["argv"][0]["type"] != "path":
        raise PilotError("runner.entry_path_required")
    if not inside(checkout, action["runner"]["argv"][0]["value"]).is_file():
        raise PilotError("runner.entry_not_file")
    return {"action": action, "action_sha256": digest(json_bytes(action)), "files": files,
            "tool": {"path": str(tool), "sha256": digest(tool.read_bytes())}}


def register(registry, checkout_id, project_id, checkout, action, tools, *, replace=False):
    identifier(checkout_id)
    identifier(project_id)
    policy_check(action)
    if action.get("project_id") != project_id:
        raise PilotError("identity.project_mismatch")
    root, common = checkout_identity(checkout)
    pinned = pin_action(root, action, tools)
    registry = Path(registry).absolute()
    private_directory(registry.parent)
    lock_path = registry.with_suffix(registry.suffix + ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_json(registry) if registry.exists() else {"schema_version": "0.1.0", "checkouts": {}}
        if (not isinstance(data, dict) or data.get("schema_version") != "0.1.0"
                or not isinstance(data.get("checkouts"), dict)):
            raise PilotError("registry.invalid")
        existing = data["checkouts"].get(checkout_id)
        if existing and (existing["root"] != str(root) or existing["project_id"] != project_id):
            raise PilotError("identity.checkout_already_registered")
        if any(item["root"] == str(root) and key != checkout_id for key, item in data["checkouts"].items()):
            raise PilotError("identity.checkout_alias")
        if any(item["git_common_dir"] == str(common) and item["project_id"] != project_id
               for item in data["checkouts"].values()):
            raise PilotError("identity.shared_repository_project_mismatch")
        entry = existing or {"checkout_id": checkout_id, "project_id": project_id, "root": str(root), "git_common_dir": str(common), "actions": {}}
        if action["action_id"] in entry["actions"] and not replace:
            raise PilotError("action.already_registered")
        entry["actions"][action["action_id"]] = pinned
        data["checkouts"][checkout_id] = entry
        atomic_json(registry, data)
    return {"registered": checkout_id, "action_id": action["action_id"]}


def load_checkout(registry, checkout_id):
    identifier(checkout_id)
    data = read_json(registry)
    if not isinstance(data, dict) or data.get("schema_version") != "0.1.0":
        raise PilotError("registry.invalid")
    try:
        entry = data["checkouts"][checkout_id]
    except (KeyError, TypeError):
        raise PilotError("checkout.not_registered") from None
    if not isinstance(entry, dict) or entry.get("checkout_id") != checkout_id:
        raise PilotError("identity.checkout_mismatch")
    root, common = checkout_identity(entry["root"])
    if str(common) != entry["git_common_dir"]:
        raise PilotError("identity.git_common_dir_changed")
    return entry


def command(entry, pinned):
    action = pinned["action"]
    policy_check(action)
    if action["project_id"] != entry["project_id"] or digest(json_bytes(action)) != pinned["action_sha256"]:
        raise PilotError("identity.action_mismatch")
    root = Path(entry["root"])
    for relative, expected in pinned["files"].items():
        if digest(inside(root, relative).read_bytes()) != expected:
            raise PilotError("source.changed_since_registration")
    tool = Path(pinned["tool"]["path"])
    if tool.is_symlink() or digest(tool.read_bytes()) != pinned["tool"]["sha256"]:
        raise PilotError("tool.changed_since_registration")
    argv = [str(tool)]
    for argument in action["runner"]["argv"]:
        argv.append(str(inside(root, argument["value"])) if argument["type"] == "path" else argument["value"])
    return argv, str(inside(root, action["runner"]["cwd"]))
