"""Tests for live-directory archive compaction."""

import shutil
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_archive import compact_managed_directory
import workspace_archive


class TestWorkspaceArchive(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="workspace_archive_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_files(self, directory: Path, count: int, suffix: str = ".txt") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for idx in range(count):
            (directory / f"{idx:04d}{suffix}").write_text(str(idx))

    def test_compacts_oldest_direct_files_into_archive_bucket(self):
        self._write_files(self.tmpdir, 7)

        buckets = compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3)

        self.assertEqual(len(buckets), 1)
        self.assertTrue(buckets[0].name.startswith("until_"))
        live_names = sorted(path.name for path in self.tmpdir.glob("*.txt"))
        archived_names = sorted(path.name for path in buckets[0].glob("*.txt"))
        self.assertEqual(live_names, ["0003.txt", "0004.txt", "0005.txt", "0006.txt"])
        self.assertEqual(archived_names, ["0000.txt", "0001.txt", "0002.txt"])

    def test_existing_archive_subtree_is_ignored(self):
        self._write_files(self.tmpdir, 7)
        self._write_files(self.tmpdir / "archive" / "until_old", 4)

        compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3)

        live_names = sorted(path.name for path in self.tmpdir.glob("*.txt"))
        old_archive_names = sorted(
            path.name for path in (self.tmpdir / "archive" / "until_old").glob("*.txt")
        )
        self.assertEqual(live_names, ["0003.txt", "0004.txt", "0005.txt", "0006.txt"])
        self.assertEqual(old_archive_names, ["0000.txt", "0001.txt", "0002.txt", "0003.txt"])

    def test_noop_when_under_cap_or_rerun(self):
        self._write_files(self.tmpdir, 6)
        self.assertEqual(
            compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3),
            [],
        )

        self._write_files(self.tmpdir, 1, ".json")
        compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3)
        second_pass = compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3)
        self.assertEqual(second_pass, [])

    def test_repeats_in_chunks_until_live_dir_is_bounded(self):
        self._write_files(self.tmpdir, 13)

        buckets = compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3)

        self.assertTrue(buckets)
        live_names = sorted(path.name for path in self.tmpdir.glob("*.txt"))
        self.assertEqual(live_names, ["0009.txt", "0010.txt", "0011.txt", "0012.txt"])

    def test_under_cap_does_not_request_mtime_metadata(self):
        self._write_files(self.tmpdir, 6)
        actual_scandir = os.scandir

        class Entry:
            def __init__(self, entry):
                self.entry = entry
                self.name, self.path = entry.name, entry.path

            def is_file(self):
                return self.entry.is_file()

            def stat(self):
                raise AssertionError("under-cap scan must not fetch mtime")

        class Scan:
            def __enter__(self):
                self.scan = actual_scandir(self_path)
                return (Entry(entry) for entry in self.scan)

            def __exit__(self, *args):
                self.scan.close()

        self_path = self.tmpdir
        with patch.object(workspace_archive.os, "scandir", side_effect=lambda path: Scan()):
            self.assertEqual(compact_managed_directory(self.tmpdir, ".txt", live_cap=6, bucket_size=3), [])

    def test_equal_mtime_preserves_filename_order_and_contents(self):
        for name in ("c.txt", "a.txt", "b.txt", "d.txt"):
            path = self.tmpdir / name
            path.write_text("original " + name)
            os.utime(path, (1_600_000_000, 1_600_000_000))
        buckets = compact_managed_directory(self.tmpdir, ".txt", live_cap=3, bucket_size=2)
        self.assertEqual(sorted(path.name for path in buckets[0].iterdir()), ["a.txt", "b.txt"])
        self.assertEqual((buckets[0] / "a.txt").read_text(), "original a.txt")
        self.assertEqual((self.tmpdir / "c.txt").read_text(), "original c.txt")

    def test_each_bucket_rescans_arrivals_before_choosing_next_oldest(self):
        self._write_files(self.tmpdir, 9)
        for index, path in enumerate(sorted(self.tmpdir.glob("*.txt"))):
            os.utime(path, (1_600_000_000 + index, 1_600_000_000 + index))
        rename = Path.rename
        moved = []

        def arrival(path, target):
            result = rename(path, target)
            moved.append(path.name)
            if len(moved) == 3:
                added = self.tmpdir / "arrival.txt"
                added.write_text("arrived during compaction")
                os.utime(added, (1_500_000_000, 1_500_000_000))
            return result

        with patch.object(Path, "rename", arrival):
            compact_managed_directory(self.tmpdir, ".txt", live_cap=4, bucket_size=3)
        self.assertEqual(moved, ["0000.txt", "0001.txt", "0002.txt", "arrival.txt", "0003.txt", "0004.txt"])
        self.assertEqual(sorted(path.name for path in self.tmpdir.glob("*.txt")),
                         ["0005.txt", "0006.txt", "0007.txt", "0008.txt"])


if __name__ == "__main__":
    unittest.main()
