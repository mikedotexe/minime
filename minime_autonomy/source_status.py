"""Bounded source-status publication; no model, queue or service authority.

Atomic replacement needs fresh space. This is not a reservation or power-loss
qualification. Mandatory retries retain exact bytes only in the owning process.
"""
import errno
import json
import os
from pathlib import Path
import stat
import sys
import threading
from uuid import uuid4

MAX_STATUS_BYTES = 1024 * 1024
STATUS_NAME = "autonomous_agent_source_status.json"
MANDATORY_REASONS = frozenset({"startup", "drained"})
IDENTITY_FIELDS = ("pid", "started_at", "boot_id", "source_inputs_at_start",
                   "next_handoff_seal", "next_handoff_restore", "lifecycle_phase", "reason")


def encode(status):
    raw = (json.dumps(status, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_STATUS_BYTES:
        raise ValueError("source_status_capacity")
    return raw


def checked_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.name != STATUS_NAME:
        raise ValueError("unsafe_source_status_path")
    # Match maintenance_next.checked: only verified macOS system aliases normalize.
    if sys.platform == "darwin":
        for alias in (Path("/var"), Path("/tmp")):
            if path.is_relative_to(alias) and alias.is_symlink():
                target = Path("/private") / alias.name
                if alias.lstat().st_uid != 0 or alias.resolve() != target:
                    raise ValueError("unexpected_system_path_alias")
                path = target / path.relative_to(alias)
                break
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("unsafe_source_status_path")
    return path


def signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode)


def read_target(directory, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:
        return None, None
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_nlink != 1 or before.st_mode & 0o022
                or before.st_size > MAX_STATUS_BYTES):
            raise ValueError("unowned_or_unbounded_source_status")
        raw = stream.read(MAX_STATUS_BYTES + 1)
        if (len(raw) > MAX_STATUS_BYTES or signature(before) != signature(os.fstat(stream.fileno()))
                or signature(before) != signature(os.stat(name, dir_fd=directory, follow_symlinks=False))):
            raise ValueError("source_status_changed")
    return raw, signature(before)


def publish(path, raw):
    """Publish or re-sync exact visible bytes; never truncate the prior target."""
    path = checked_path(path)
    if not isinstance(raw, bytes) or len(raw) > MAX_STATUS_BYTES:
        raise ValueError("source_status_capacity")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    temporary = None
    try:
        for index, part in enumerate(path.parent.parts[1:]):
            last = index == len(path.parent.parts) - 2
            if last:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
                # Retry this barrier even if a previous mkdir became visible.
                os.fsync(directory)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        parent = os.fstat(directory)
        if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
            raise ValueError("unowned_source_status_directory")
        previous, identity = read_target(directory, path.name)
        if previous != raw:
            temporary = ".source-status-" + uuid4().hex
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            try:
                offset = 0
                while offset < len(raw):
                    count = os.write(fd, raw[offset:])
                    if count <= 0:
                        raise OSError(errno.EIO, "source status write made no progress")
                    offset += count
                os.fsync(fd)
            finally:
                os.close(fd)
            if read_target(directory, path.name) != (previous, identity):
                raise ValueError("source_status_changed")
            checked_path(path)
            if (parent.st_dev, parent.st_ino) != (path.parent.stat().st_dev, path.parent.stat().st_ino):
                raise ValueError("source_status_directory_changed")
            os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            temporary = None
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        try:
            if read_target(directory, path.name)[0] != raw:
                raise ValueError("source_status_changed")
            if signature(os.fstat(fd)) != signature(os.stat(path.name, dir_fd=directory, follow_symlinks=False)):
                raise ValueError("source_status_changed")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
        checked_path(path)
        if ((parent.st_dev, parent.st_ino) != (path.parent.stat().st_dev, path.parent.stat().st_ino)
                or read_target(directory, path.name)[0] != raw):
            raise ValueError("source_status_changed")
    finally:
        try:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory)


class Publisher:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = None

    def write(self, path, status, *, mandatory):
        with self.lock:
            if self.pending is not None:
                if not mandatory:
                    return status  # A heartbeat cannot replace an unacknowledged mandatory record.
                saved_path, raw = self.pending
                saved = json.loads(raw)
                if Path(path) != saved_path or any(saved.get(k) != status.get(k) for k in IDENTITY_FIELDS):
                    raise ValueError("source_status_retry_conflict")
            else:
                raw = encode(status)
                if mandatory:
                    self.pending = (Path(path), raw)
            publish(path, raw)
            self.pending = None
            return json.loads(raw)
