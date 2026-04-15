"""Tests for live-directory archive compaction."""

import shutil
import tempfile
import unittest
from pathlib import Path

from workspace_archive import compact_managed_directory


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


if __name__ == "__main__":
    unittest.main()
