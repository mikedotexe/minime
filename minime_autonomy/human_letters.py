"""Bounded, explicit human envelopes; no runtime, delivery log, or live defaults.

Preview preserves the authored UTF-8 bytes. Submission publishes into the
explicit, existing workspace's inbox with private publication receipts; it does
not claim the runtime read it.
The 12,000-character ceiling mirrors INBOX_STEWARD_LETTER_MAX_CHARS without
importing runtime, and conservatively includes the entire envelope.
"""

from contextlib import ExitStack
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from .mailbox_fs import Directory


MAX_LETTER_CHARS = 12_000
MAX_SOURCE_BYTES = MAX_LETTER_CHARS * 4
_ID = re.compile(r"[A-Za-z0-9_-]{1,120}")
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class HumanLetterError(ValueError):
    """A safe-to-display error that never includes authored content."""


@dataclass(frozen=True)
class HumanLetter:
    sender: str
    message_id: str
    thread_id: str
    body: bytes = field(repr=False)

    def __post_init__(self):
        _validate_address(self.sender, self.message_id, self.thread_id)
        if not isinstance(self.body, bytes):
            raise HumanLetterError("Source must be plain UTF-8 bytes.")
        if len(self.body) > MAX_SOURCE_BYTES:
            raise HumanLetterError("Source exceeds the bounded UTF-8 input size.")
        try:
            text = self.body.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise HumanLetterError(
                "Source is not valid UTF-8; export a separate plain UTF-8 text file."
            ) from None
        if text.lstrip("\ufeff \t\r\n").lower().startswith("{\\rtf"):
            raise HumanLetterError(
                "Source is RTF, even if named .txt; export a separate plain UTF-8 "
                "text file. RTF is not converted and the source is untouched."
            )
        if any((ord(char) < 32 and char not in "\t\r\n")
               or 127 <= ord(char) <= 159 for char in text):
            raise HumanLetterError("Source contains non-plain-text control characters.")
        if not text.strip("\ufeff \t\r\n"):
            raise HumanLetterError("Source must contain a nonempty plain-text letter.")
        if len(self.header) + len(text) > MAX_LETTER_CHARS:
            raise HumanLetterError(
                f"Letter exceeds {MAX_LETTER_CHARS:,} characters including the "
                f"envelope; body allowance is {MAX_LETTER_CHARS - len(self.header):,}."
            )

    @property
    def header(self) -> bytes:
        return (
            "=== HUMAN LETTER V1 ===\n"
            f"Message-Id: {self.message_id}\n"
            f"Thread-Id: {self.thread_id}\n"
            f"From: {self.sender}\n"
            "To: minime\n\n"
        ).encode("ascii")

    @property
    def content(self) -> bytes:
        return self.header + self.body

    @property
    def filename(self) -> str:
        return f"human_letter_{self.message_id}.txt"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class Submission:
    """Publication result; a previously published path may already be consumed."""

    path: Path
    sha256: str
    created: bool


def _validate_address(sender, message_id, thread_id):
    if sender not in ("mike", "steward"):
        raise HumanLetterError("Sender must be explicitly 'mike' or 'steward'.")
    for label, value in (("Message ID", message_id), ("Thread ID", thread_id)):
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise HumanLetterError(
                f"{label} must contain 1-120 ASCII letters, digits, '_' or '-'."
            )


def _path(value) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError:
        raise HumanLetterError("An explicit filesystem path is required.") from None
    if not isinstance(raw, str) or not raw or "\0" in raw or ".." in raw.split("/"):
        raise HumanLetterError("Paths must be explicit and must not contain '..' or NUL.")
    # Do not resolve(): that would silently accept symlinked ancestors.
    return Path(os.path.abspath(raw))


def _identity(info):
    return info.st_dev, info.st_ino


def _snapshot(info):
    return _identity(info), info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _check_entry(parent, name, expected):
    actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if (_identity(actual) != _identity(expected)
            or stat.S_IFMT(actual.st_mode) != stat.S_IFMT(expected.st_mode)):
        raise HumanLetterError("Filesystem entry changed during access; retry a fresh preview.")


class _Directory:
    """Pin every ancestor, so a rename or symlink swap cannot redirect I/O."""

    def __init__(self, path, stack):
        self.stack = stack
        self.links = []
        self.fd = os.open("/", _DIRECTORY_FLAGS)
        stack.callback(os.close, self.fd)
        for name in path.parts[1:]:
            self.descend(name)

    def descend(self, name):
        child = os.open(name, _DIRECTORY_FLAGS, dir_fd=self.fd)
        self.stack.callback(os.close, child)
        self.links.append((self.fd, name, os.fstat(child)))
        self.fd = child
        self.check()

    def check(self):
        for parent, name, expected in self.links:
            _check_entry(parent, name, expected)


def _read_regular(fd):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise HumanLetterError("Only regular files are accepted; no symlinks or special files.")
    if before.st_size > MAX_SOURCE_BYTES:
        raise HumanLetterError("File exceeds the bounded UTF-8 input size (48,000 bytes).")
    chunks = []
    remaining = MAX_SOURCE_BYTES + 1
    while remaining:
        chunk = os.read(fd, min(8192, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    after = os.fstat(fd)
    if _snapshot(before) != _snapshot(after):
        raise HumanLetterError("File changed while reading; retry a fresh preview.")
    if not remaining:
        raise HumanLetterError("File exceeds the bounded UTF-8 input size (48,000 bytes).")
    return b"".join(chunks), after


def preview_letter(source, *, sender, message_id, thread_id) -> HumanLetter:
    """Read a bounded regular file without normalizing or modifying its bytes."""
    _validate_address(sender, message_id, thread_id)
    path = _path(source)
    try:
        with ExitStack() as stack:
            directory = _Directory(path.parent, stack)
            fd = os.open(path.name, _READ_FLAGS, dir_fd=directory.fd)
            stack.callback(os.close, fd)
            body, info = _read_regular(fd)
            _check_entry(directory.fd, path.name, info)
            directory.check()
            return HumanLetter(sender, message_id, thread_id, body)
    except OSError as exc:
        raise HumanLetterError(
            f"Cannot safely read source ({exc.strerror}); use an existing regular "
            "file and paths with no symlink components."
        ) from None


def _existing(directory, letter):
    try:
        fd = os.open(letter.filename, _READ_FLAGS, dir_fd=directory.fd)
    except FileNotFoundError:
        return False
    try:
        content, info = _read_regular(fd)
        if content != letter.content:
            raise HumanLetterError(
                "Destination conflict: this message ID already has different bytes; "
                "nothing was overwritten. Use a new explicit ID for a new letter."
            )
        _check_entry(directory.fd, letter.filename, info)
        os.fsync(fd)
        if _snapshot(os.fstat(fd)) != _snapshot(info):
            raise HumanLetterError("Destination changed during replay; submission not confirmed.")
        _check_entry(directory.fd, letter.filename, info)
        directory.check()
        return True
    finally:
        os.close(fd)


def _publish(directory, letter):
    """Fsync complete bytes before an atomic, no-replace hard-link publication."""
    temporary = f".human_letter_{uuid4().hex}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory.fd)
    info = os.fstat(fd)
    try:
        content = memoryview(letter.content)
        while content:
            written = os.write(fd, content)
            if written <= 0:
                raise HumanLetterError("Incomplete write; submission not confirmed.")
            content = content[written:]
        os.fsync(fd)
        directory.check()
        _check_entry(directory.fd, temporary, info)
        try:
            os.link(temporary, letter.filename, src_dir_fd=directory.fd,
                    dst_dir_fd=directory.fd, follow_symlinks=False)
        except FileExistsError:
            if not _existing(directory, letter):
                raise HumanLetterError("Destination raced with submission; retry explicitly.")
            return False
        _check_entry(directory.fd, letter.filename, info)
        directory.check()
        return True
    finally:
        os.close(fd)
        # Only our unpredictable staging name is removed, never a source/letter.
        try:
            _check_entry(directory.fd, temporary, info)
            os.unlink(temporary, dir_fd=directory.fd)
        except FileNotFoundError:
            pass
        os.fsync(directory.fd)


def _publish_once(root, directory, letter):
    receipts = root.child("correspondence", create=True).child(
        "human_letter_publications_v1", create=True)
    identity = hashlib.sha256(("inbox/" + letter.filename).encode("ascii")).hexdigest()
    metadata = json.dumps({"schema": "human_letter_publication_v1",
                           "sha256": letter.sha256}, sort_keys=True).encode("ascii")
    with receipts.lock(".publication.lock"):
        receipt = receipts.child(identity, create=True)
        if receipt.created:
            receipt.atomic("intent.json", metadata)
        elif not receipt.exists("intent.json"):
            raise HumanLetterError("Publication history incomplete; reconcile without republishing.")
        if receipt.read("intent.json", 4096) != metadata:
            raise HumanLetterError("Destination conflict: publication identity already has different bytes.")
        if receipt.exists("published.json"):
            if receipt.read("published.json", 4096) != metadata:
                raise HumanLetterError("Publication receipt conflict; reconcile without republishing.")
            # Missing output after confirmed publication can mean consumption.
            _existing(directory, letter)
            receipt.sync()
            return False
        if not receipt.created:
            if not _existing(directory, letter):
                raise HumanLetterError("Publication uncertain; reconcile without republishing.")
            created = False
        else:
            created = False if _existing(directory, letter) else _publish(directory, letter)
        os.fsync(directory.fd)
        if not _existing(directory, letter):
            raise HumanLetterError("Publication uncertain; reconcile without republishing.")
        receipt.atomic("published.json", metadata)
        return created


def submit_letter(letter: HumanLetter, *, workspace, confirm_sha256: str) -> Submission:
    """Require preview's SHA-256, then publish once or accept exact-byte replay.

    The workspace must already exist; its inbox and private correspondence
    receipt directories may be created. No path
    component may be a symlink (on macOS use /private/tmp, not /tmp). Directory
    descriptors pin I/O and identity checks detect concurrent replacements.
    Durable receipts suppress replay even after consumption. After an interrupted
    publication, exact visible bytes can complete the receipt; missing output
    requires reconciliation, never blind republishing. Sources and archives are
    never removed or overwritten.
    """
    if (not isinstance(confirm_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", confirm_sha256)
            or not hmac.compare_digest(confirm_sha256, letter.sha256)):
        raise HumanLetterError("Confirmation SHA-256 must exactly match a fresh preview.")
    path = _path(workspace)
    try:
        with Directory(path) as root:
            directory = root.child("inbox", create=True)
            created = _publish_once(root, directory, letter)
            directory.check()
            return Submission(path / "inbox" / letter.filename, letter.sha256, created)
    except HumanLetterError:
        raise
    except ValueError:
        raise HumanLetterError(
            "Filesystem entry changed or receipt is unsafe; submission not confirmed."
        ) from None
    except OSError as exc:
        raise HumanLetterError(
            f"Submission not confirmed ({exc.strerror}); workspace must exist and "
            "all components must be real directories/regular files, not symlinks. "
            "Retry only with the same confirmed bytes; uncertainty requires reconciliation. "
            "No existing letter is overwritten."
        ) from None
