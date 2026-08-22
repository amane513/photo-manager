import logging
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager.config import ArchiveVolume, Config
from photo_manager.discovery import SourceFile, SourceKind
from photo_manager.importer import ImportSummary, import_handler, should_eject
from photo_manager.metadata import CaptureTime
from photo_manager.naming import PlannedAction, TransferPlan
from photo_manager.runtime import RunResources


class ImportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source_root = self.root / "card"
        self.source = self.source_root / "DCIM" / "100MSDCF" / "DSC00001.JPG"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"source bytes")
        self.destination = self.root / "archive"
        self.destination.mkdir()
        self.config = Config(ArchiveVolume(self.destination, "archive-uuid"), self.source_root, None,
                             Path("/usr/bin/exiftool"), "sha256", 1.0, True)
        source_file = SourceFile(self.source, SourceKind.STILL, self.source.stat().st_size, self.source.stat().st_mtime)
        capture = CaptureTime(datetime(2026, 8, 22, 10, 0, 0), "test")
        relative = Path("Camera/2026/2026-08/20260822_100000_DSC00001.JPG")
        self.plan = TransferPlan(source_file, capture, self.destination / relative, relative, PlannedAction.COPY, False)
        self.args = SimpleNamespace(config=None, dry_run=False, source=None, dest=None, dest_volume_uuid=None, no_eject=False)
        self.logger = logging.getLogger("test-import")
        self.logger.handlers[:] = [logging.NullHandler()]

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, *, dry_run=False):
        self.args.dry_run = dry_run
        resources = RunResources(self.logger)
        with mock.patch("photo_manager.importer.load_config", return_value=self.config), \
             mock.patch("photo_manager.importer.validate_volume"), \
             mock.patch("photo_manager.importer.ensure_exiftool"), \
             mock.patch("photo_manager.importer._build_plans", return_value=((self.plan,), 0, 0)):
            status = import_handler(self.args, resources, self.logger)
        resources.cleanup()
        return status

    def test_dry_run_does_not_create_archive_management_state_or_eject(self):
        before_source = self.source.read_bytes()
        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(dry_run=True), 0)
        self.assertEqual(self.source.read_bytes(), before_source)
        self.assertFalse((self.destination / "_photo-manager").exists())
        self.assertFalse(self.plan.destination.exists())
        eject.assert_not_called()

    def test_copy_records_and_ejects_only_after_final_recheck(self):
        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(), 0)
        self.assertEqual(self.source.read_bytes(), b"source bytes")
        self.assertEqual(self.plan.destination.read_bytes(), b"source bytes")
        self.assertTrue((self.destination / "_photo-manager" / "checksums.tsv").is_file())
        eject.assert_called_once_with(self.source_root)

    def test_eject_policy_requires_every_independent_condition(self):
        self.assertTrue(should_eject(ImportSummary(ledger_complete=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=False), enabled=True))
        self.assertFalse(should_eject(ImportSummary(failures=1, ledger_complete=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=True, dry_run=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=True), enabled=False))
