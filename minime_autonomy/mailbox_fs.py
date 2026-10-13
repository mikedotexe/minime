"""Pinned POSIX filesystem operations for correspondence, never runtime policy."""

from contextlib import ExitStack, contextmanager
import fcntl
import os
from pathlib import Path
import stat
from uuid import uuid4


class FileTooLarge(ValueError):
    pass


def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _snapshot(info):
    return _identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _name(name):
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\0" in name:
        raise ValueError("unsafe correspondence filename")
    return name


class Directory:
    """All I/O is relative to held descriptors; every ancestor rejects symlinks.

    Children share the root's lifetime. Identity checks detect renamed paths;
    even a replacement between checks cannot redirect an operation elsewhere.
    """

    def __init__(self, path, *, create=False):
        raw = os.fspath(path)
        if not isinstance(raw, str) or not raw or ".." in raw.split("/") or "\0" in raw:
            raise ValueError("unsafe correspondence directory")
        self.path = Path(os.path.abspath(raw))
        self.stack = ExitStack()
        self.links = []
        self.fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.stack.callback(os.close, self.fd)
        try:
            for name in self.path.parts[1:]:
                self.fd, _ = self._descend(name, create)
        except BaseException:
            self.stack.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def _descend(self, name, create):
        created = False
        self.check()
        if create:
            try:
                os.mkdir(name, mode=0o700, dir_fd=self.fd)
                os.fsync(self.fd)
                created = True
            except FileExistsError:
                pass
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=self.fd)
        self.stack.callback(os.close, child)
        self.links.append((self.fd, name, os.fstat(child)))
        self.check()
        return child, created

    def child(self, name, *, create=False):
        name = _name(name)
        child = object.__new__(Directory)
        child.path, child.stack = self.path / name, self.stack
        child.links, child.fd = list(self.links), self.fd
        child.fd, child.created = child._descend(name, create)
        return child

    def check(self):
        for parent, name, expected in self.links:
            actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if _identity(actual) != _identity(expected):
                raise ValueError("correspondence directory changed; reconciliation required")

    def stat(self, name):
        self.check()
        return os.stat(_name(name), dir_fd=self.fd, follow_symlinks=False)

    def exists(self, name):
        try:
            self.stat(name)
            return True
        except FileNotFoundError:
            self.check()
            return False

    def names(self):
        self.check()
        names = os.listdir(self.fd)
        self.check()
        return names

    def sync(self):
        os.fsync(self.fd)
        self.check()

    def read(self, name, limit):
        self.check()
        fd = os.open(_name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=self.fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("correspondence artifact is not a regular file")
            if before.st_size > limit:
                raise FileTooLarge("correspondence artifact exceeds its byte limit")
            chunks, remaining = [], limit + 1
            while remaining:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            if not remaining:
                raise FileTooLarge("correspondence artifact exceeds its byte limit")
            if (_snapshot(before) != _snapshot(os.fstat(fd))
                    or _snapshot(before) != _snapshot(self.stat(name))):
                raise ValueError("correspondence artifact changed during read")
            return b"".join(chunks)
        finally:
            os.close(fd)

    def atomic(self, name, data, *, replace=False):
        """Fsync staging bytes, then publish atomically; never truncate a target."""
        name = _name(name)
        self.check()
        temporary = f".mailbox-{uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        identity = _identity(os.fstat(fd))
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("incomplete correspondence write")
                view = view[written:]
            os.fsync(fd)
            self.check()
            if _identity(self.stat(temporary)) != identity:
                raise ValueError("correspondence staging file changed")
            if replace:
                if self.exists(name) and not stat.S_ISREG(self.stat(name).st_mode):
                    raise ValueError("correspondence target is not a regular file")
                os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            else:
                try:
                    os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd,
                            follow_symlinks=False)
                except FileExistsError:
                    if self.read(name, max(len(data), 1)) != data:
                        raise ValueError("correspondence immutable artifact conflict; retained unchanged")
            self.sync()
        finally:
            os.close(fd)
            # Cleanup is confined to our random staging name, never an authored source.
            try:
                if _identity(os.stat(temporary, dir_fd=self.fd, follow_symlinks=False)) != identity:
                    raise ValueError("correspondence staging file changed")
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass
            os.fsync(self.fd)

    @contextmanager
    def lock(self, name):
        self.check()
        fd = os.open(_name(name), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
                     | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("correspondence lock is not a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            if _identity(self.stat(name)) != _identity(os.fstat(fd)):
                raise ValueError("correspondence lock changed")
            yield
            self.check()
        finally:
            os.close(fd)

    def append(self, name, data):
        self.check()
        fd = os.open(_name(name), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
                     | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("correspondence ledger is not a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            if _identity(self.stat(name)) != _identity(os.fstat(fd)):
                raise ValueError("correspondence ledger changed")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("incomplete correspondence ledger write")
                view = view[written:]
            os.fsync(fd)
            self.sync()
        finally:
            os.close(fd)


def letter_text(raw, character_limit):
    """Return text or a content-free rejection category; never convert RTF."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return None, "invalid_utf8"
    leading = text.lstrip("\ufeff \t\r\n")
    if leading.lower().startswith("{\\rtf"):
        return None, "rtf"
    if not leading.strip():
        return None, "empty"
    if len(text) > character_limit:
        return None, "oversize"
    return text, None
