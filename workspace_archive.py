"""Helpers for keeping live workspace directories bounded.

Managed directories keep recent files in the live root and move older files
into timestamped archive buckets once the live count crosses a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


DEFAULT_LIVE_CAP = 6_000
DEFAULT_BUCKET_SIZE = 3_000


@dataclass(frozen=True)
class ManagedDirectoryConfig:
    suffix: str
    live_cap: int = DEFAULT_LIVE_CAP
    bucket_size: int = DEFAULT_BUCKET_SIZE


def compact_managed_directory(
    directory: Path,
    suffix: str,
    live_cap: int = DEFAULT_LIVE_CAP,
    bucket_size: int = DEFAULT_BUCKET_SIZE,
) -> list[Path]:
    """Move oldest direct files into archive buckets until the live dir is bounded."""
    config = ManagedDirectoryConfig(
        suffix=suffix,
        live_cap=live_cap,
        bucket_size=bucket_size,
    )
    return _compact(directory, config)


def _compact(directory: Path, config: ManagedDirectoryConfig) -> list[Path]:
    if config.live_cap <= 0 or config.bucket_size <= 0 or not directory.is_dir():
        return []

    created_buckets: list[Path] = []
    archive_root = directory / "archive"

    while True:
        live_files = _live_files(directory, config.suffix)
        if len(live_files) <= config.live_cap:
            return created_buckets

        bucket_files = live_files[: config.bucket_size]
        newest_moved = bucket_files[-1]
        timestamp = datetime.fromtimestamp(newest_moved.stat().st_mtime).strftime(
            "%Y-%m-%dT%H-%M-%S"
        )
        bucket_dir = archive_root / f"until_{timestamp}"
        bucket_dir.mkdir(parents=True, exist_ok=True)

        for path in bucket_files:
            path.rename(bucket_dir / path.name)

        if not created_buckets or created_buckets[-1] != bucket_dir:
            created_buckets.append(bucket_dir)


def _live_files(directory: Path, suffix: str) -> list[Path]:
    paths = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix == suffix
    ]
    paths.sort(key=lambda path: (path.stat().st_mtime, path.name))
    return paths
