"""Private local evidence and bounded path operations."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,95}\Z")


class PilotError(ValueError):
    """A fixed, non-sensitive reason safe to return to the CLI."""


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise PilotError("identity.invalid")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode()


def private_directory(path):
    path = Path(path)
    # Reject symlinks throughout the managed path, including dangling links.
    for candidate in (*reversed(path.parents), path):
        if candidate.is_symlink():
            raise PilotError("storage.symlink")
    for candidate in (*reversed(path.parents), path):
        if not candidate.exists():
            candidate.mkdir(mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise PilotError("storage.not_owned")
    return path


def atomic_json(path, value):
    path = Path(path)
    private_directory(path.parent)
    if path.is_symlink():
        raise PilotError("storage.symlink")
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def decode_json(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("non-finite JSON value")

    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def read_json(path, limit=MAX_ARTIFACT_BYTES):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise PilotError("storage.invalid_file")
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise PilotError("storage.file_too_large")
        return decode_json(data)
    except (UnicodeError, ValueError):
        raise PilotError("storage.invalid_json") from None


def inside(root, relative, *, must_exist=True):
    """Resolve a declared relative path and reject traversal or symlink escape."""
    root = Path(root).resolve(strict=True)
    if (not isinstance(relative, str) or not relative or Path(relative).is_absolute()
            or ".." in Path(relative).parts or "\\" in relative or ":" in relative
            or any(ord(character) < 32 for character in relative)):
        raise PilotError("path.invalid")
    try:
        target = (root / relative).resolve(strict=must_exist)
    except (OSError, RuntimeError):
        raise PilotError("path.missing") from None
    if not target.is_relative_to(root):
        raise PilotError("path.outside_checkout")
    return target


def write_private(path, data):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
