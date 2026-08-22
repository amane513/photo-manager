import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager.config import ArchiveVolume, Config
from photo_manager.ledger import LedgerError, load_ledger, make_record, replace_ledger
from photo_manager.mirror import mirror_handler
from photo_manager.runtime import RunResources
from photo_manager.volumes import VolumeInfo


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "primary"
        self.target = self.root / "mirror"
        self.source.mkdir()
        self.target.mkdir()
        self.relative = "Camera/2026/2026-08/20260822_120000_DSC00001.JPG"
        self.source_file = self.source / self.relative
        self.source_file.parent.mkdir(parents=True)
        self.source_file.write_bytes(b"verified primary data")
        record = make_record(self.relative, __import__("hashlib").sha256(self.source_file.read_bytes()).hexdigest(),
                             self.source_file.stat().st_size, datetime(2026, 8, 22, 12, tzinfo=timezone.utc))
        replace_ledger(self.source, [record])
        self.config = Config(ArchiveVolume(self.source, "source-uuid"), None,
                             ArchiveVolume(self.target, "target-uuid"), Path("/bin/true"), "sha256", 1.0, False)
        self.logger = logging.getLogger("test_mirror")

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, dry_run=False):
        args = SimpleNamespace(config=None, dry_run=dry_run)
        resources = RunResources(self.logger)
        infos = [VolumeInfo(self.source, "source-uuid", "disk1s1", "disk1"),
                 VolumeInfo(self.target, "target-uuid", "disk2s1", "disk2")]
        with mock.patch("photo_manager.mirror.load_config", return_value=self.config), \
             mock.patch("photo_manager.mirror.validate_volume", side_effect=infos):
            try:
                return mirror_handler(args, resources, self.logger)
            finally:
                resources.cleanup()

    def test_empty_target_is_copied_and_ledger_is_snapshot(self):
        self.assertEqual(self._run(), 0)
        target_file = self.target / self.relative
        self.assertEqual(target_file.read_bytes(), self.source_file.read_bytes())
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))

    def test_bad_source_does_not_change_target(self):
        self.source_file.write_bytes(b"corrupted after import")
        self.assertEqual(self._run(), 1)
        self.assertFalse((self.target / self.relative).exists())
        self.assertFalse((self.target / "_photo-manager").exists())

    def test_conflicting_target_is_not_overwritten(self):
        target_file = self.target / self.relative
        target_file.parent.mkdir(parents=True)
        target_file.write_bytes(b"different and retained")
        self.assertEqual(self._run(), 1)
        self.assertEqual(target_file.read_bytes(), b"different and retained")
        self.assertFalse((self.target / "_photo-manager").exists())

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self._run(dry_run=True), 0)
        self.assertFalse((self.target / self.relative).exists())
        self.assertFalse((self.target / "_photo-manager").exists())

    def test_extra_target_file_is_retained(self):
        extra = self.target / "Camera/2025/2025-01/kept.JPG"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"keep")
        self.assertEqual(self._run(), 0)
        self.assertEqual(extra.read_bytes(), b"keep")

    def test_retries_existing_verified_file_after_ledger_publish_failure(self):
        with mock.patch("photo_manager.mirror.replace_ledger", side_effect=LedgerError("simulated ledger failure")):
            self.assertEqual(self._run(), 1)
        target_file = self.target / self.relative
        self.assertEqual(target_file.read_bytes(), self.source_file.read_bytes())
        self.assertFalse((self.target / "_photo-manager/checksums.tsv").exists())
        self.assertEqual(self._run(), 0)
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))
