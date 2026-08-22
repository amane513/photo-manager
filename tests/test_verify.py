import hashlib
import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager.config import ArchiveVolume, Config
from photo_manager.ledger import append_record, make_record
from photo_manager.runtime import RunResources
from photo_manager.verify import verify_handler


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "archive"
        self.root.mkdir()
        self.config = Config(ArchiveVolume(self.root, "archive-uuid", "Library/Camera"), None, None,
                             Path("/usr/bin/exiftool"), "sha256", 1.0, True)
        self.logger = logging.getLogger("test-verify")
        self.logger.handlers[:] = [logging.NullHandler()]

    def tearDown(self):
        self.temp.cleanup()

    def _add(self, relative, content=b"photo"):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        append_record(self.root, make_record(relative, hashlib.sha256(content).hexdigest(), len(content),
                                             datetime(2026, 8, 22, 10, 0, 0, tzinfo=timezone.utc)))
        return path

    def _run(self, *, year=None, month=None):
        args = SimpleNamespace(config=None, dest=None, dest_volume_uuid=None, year=year, month=month)
        resources = RunResources(self.logger)
        with mock.patch("photo_manager.verify.load_config", return_value=self.config), \
             mock.patch("photo_manager.verify.validate_volume"):
            result = verify_handler(args, resources, self.logger)
        resources.cleanup()
        return result

    def test_month_year_and_all_scopes_use_relative_archive_paths(self):
        august = "Library/Camera/2026/2026-08/20260822_100000_A.JPG"
        september = "Library/Camera/2026/2026-09/20260901_100000_B.JPG"
        other_year = "Library/Camera/2025/2025-08/20250801_100000_C.JPG"
        self._add(august)
        self._add(september)
        self._add(other_year)
        (self.root / september).write_bytes(b"corrupt")
        self.assertEqual(self._run(month="2026-08"), 0)
        self.assertEqual(self._run(year="2026"), 1)
        self.assertEqual(self._run(), 1)

    def test_missing_size_hash_and_unregistered_are_failures_but_extra_is_warning(self):
        missing = "Library/Camera/2026/2026-08/missing.JPG"
        append_record(self.root, make_record(missing, hashlib.sha256(b"x").hexdigest(), 1,
                                             datetime(2026, 8, 1, tzinfo=timezone.utc)))
        sized = self._add("Library/Camera/2026/2026-08/sized.JPG", b"abc")
        sized.write_bytes(b"too long")
        unregistered = self.root / "Library/Camera/2026/2026-08/new.JPG"
        unregistered.write_bytes(b"new")
        (self.root / "notes.txt").write_text("outside archive", encoding="utf-8")
        self.assertEqual(self._run(month="2026-08"), 1)

    def test_verify_does_not_change_files_or_ledger_and_ignores_part(self):
        path = self._add("Library/Camera/2026/2026-08/photo.JPG")
        part = path.with_name("old.JPG.part")
        part.write_bytes(b"unfinished")
        ledger = self.root / "_photo-manager/checksums.tsv"
        before = (path.read_bytes(), part.read_bytes(), ledger.read_bytes())
        self.assertEqual(self._run(month="2026-08"), 0)
        self.assertEqual(before, (path.read_bytes(), part.read_bytes(), ledger.read_bytes()))

    def test_invalid_ledger_and_invalid_range_fail(self):
        ledger = self.root / "_photo-manager/checksums.tsv"
        ledger.parent.mkdir()
        ledger.write_text("bad\trow\n", encoding="utf-8")
        self.assertEqual(self._run(), 1)
        ledger.unlink()
        with self.assertRaises(Exception):
            self._run(month="2026-13")
