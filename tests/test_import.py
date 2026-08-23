import hashlib
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager import importer as importer_module
from photo_manager import naming
from photo_manager.cli import main
from photo_manager.config import ArchiveVolume, Config
from photo_manager.importer import (ImportSummary, VerifiedTransfer, _verify_records, import_handler,
                                    should_eject)
from photo_manager.discovery import SourceFile, SourceKind
from photo_manager.ledger import append_record, make_record
from photo_manager.locking import acquire_lock
from photo_manager.metadata import CaptureTime
from photo_manager.naming import DigestCache, PlannedAction, TransferPlan
from photo_manager.runtime import RunInterrupted, RunResources, UsageError
from photo_manager.transfer import management_tmp_dir
from photo_manager.volumes import ensure_hard_links, ensure_writable


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

    def _run(self, *extra, dry_run=False):
        self.args.dry_run = dry_run
        resources = RunResources(self.logger)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("photo_manager.importer.load_config", return_value=self.config))
            stack.enter_context(mock.patch("photo_manager.importer.validate_volume"))
            stack.enter_context(mock.patch("photo_manager.importer.ensure_exiftool"))
            stack.enter_context(mock.patch("photo_manager.importer._build_plans", return_value=((self.plan,), 0, 0)))
            for patcher in extra:
                stack.enter_context(patcher)
            status = import_handler(self.args, resources, self.logger)
        resources.cleanup()
        return status

    def _counting_sha256(self, hashed):
        """Patch that records every file hashed through ``naming.sha256_file``."""
        original = naming.sha256_file

        def counted(path, **kwargs):
            hashed.append(Path(path))
            return original(path, **kwargs)

        return mock.patch("photo_manager.naming.sha256_file", counted)

    def _before_the_final_recheck(self, action):
        """Patch that runs ``action`` just before the eject-time recheck.

        The final reload is the only ``load_ledger`` call import makes with no
        keyword arguments, which makes it a precise seam for "everything was
        copied and recorded, but nothing has been rechecked yet".
        """
        original = importer_module.load_ledger

        def reloading(root, **kwargs):
            if not kwargs:
                action()
            return original(root, **kwargs)

        return mock.patch("photo_manager.importer.load_ledger", reloading)

    def _retime(self, path, contents):
        """Replace contents and move the mtime, as an external writer would."""
        path.write_bytes(contents)
        stamp = path.stat().st_mtime + 10
        os.utime(str(path), (stamp, stamp))

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

    def test_copied_file_is_only_rehashed_at_the_destination_before_eject(self):
        hashed = []
        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(self._counting_sha256(hashed)), 0)
        # The copy itself verified the source while reading it, so the eject
        # recheck re-reads the archive file and nothing else.
        self.assertEqual(hashed, [self.plan.destination])
        eject.assert_called_once_with(self.source_root)

    def test_a_temporary_left_behind_is_a_warning_and_still_records_and_ejects(self):
        part = management_tmp_dir(self.destination) / (self.plan.destination.name + ".part")
        real_unlink = Path.unlink

        def refuse_part(path, *args, **kwargs):
            if path == part:
                raise OSError(13, "Permission denied")
            return real_unlink(path, *args, **kwargs)

        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            with self.assertLogs(self.logger, level="INFO") as captured:
                status = self._run(mock.patch.object(Path, "unlink", refuse_part))
        self.assertEqual(status, 0)
        # The copy is complete: the file is published and recorded, and the
        # only unfinished business is a temporary the run's cleanup retried.
        self.assertEqual(self.plan.destination.read_bytes(), b"source bytes")
        ledger = (self.destination / "_photo-manager" / "checksums.tsv").read_text()
        self.assertIn(self.plan.relative_destination.as_posix(), ledger)
        eject.assert_called_once_with(self.source_root)
        self.assertIn("Import summary: copied 1 / skipped 0 / warning 1 / failure 0", "\n".join(captured.output))
        self.assertFalse(part.exists())

    def test_source_changed_after_the_copy_is_rehashed_and_blocks_the_eject(self):
        hashed = []
        tamper = self._before_the_final_recheck(lambda: self._retime(self.source, b"tampered!!!!"))
        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(self._counting_sha256(hashed), tamper), 1)
        self.assertIn(self.source, hashed)
        self.assertIn(self.plan.destination, hashed)
        eject.assert_not_called()

    def test_destination_changed_after_recording_blocks_the_eject(self):
        hashed = []
        tamper = self._before_the_final_recheck(
            lambda: self.plan.destination.write_bytes(b"tampered!!!!"))
        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(self._counting_sha256(hashed), tamper), 1)
        self.assertIn(self.plan.destination, hashed)
        eject.assert_not_called()

    def test_ledger_digest_disagreeing_with_the_file_blocks_the_eject(self):
        def rewrite_record():
            ledger = self.destination / "_photo-manager" / "checksums.tsv"
            row = ledger.read_text(encoding="utf-8").split("\t")
            row[2] = "b" * 64
            ledger.write_text("\t".join(row), encoding="utf-8")

        with mock.patch("photo_manager.volumes.eject_volume") as eject:
            self.assertEqual(self._run(self._before_the_final_recheck(rewrite_record)), 1)
        eject.assert_not_called()

    def test_eject_policy_requires_every_independent_condition(self):
        self.assertTrue(should_eject(ImportSummary(ledger_complete=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=False), enabled=True))
        self.assertFalse(should_eject(ImportSummary(failures=1, ledger_complete=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=True, dry_run=True), enabled=True))
        self.assertFalse(should_eject(ImportSummary(ledger_complete=True), enabled=False))

    def _seed_management_state(self):
        """Create a repairable ledger tail and a tool-owned stale ``.part``.

        Both are things import may only change *after* it holds the lock, so
        they show whether a preflight failure stopped early enough.
        """
        management = self.destination / "_photo-manager"
        (management / "tmp").mkdir(parents=True)
        ledger = management / "checksums.tsv"
        complete = "Camera/2026/2026-08/20260101_000000_OLD.JPG\tsha256\t{0}\t3\t2026-01-01T00:00:00\t2026-01-01T00:00:00+09:00\n".format("a" * 64)
        ledger.write_text(complete + "Camera/2026/2026-08/20260102_0", encoding="utf-8")
        stale = management / "tmp" / "20260101_000000_OLD.JPG.part"
        stale.write_bytes(b"stale")
        return ledger, stale

    def _management_entries(self):
        management = self.destination / "_photo-manager"
        if not management.is_dir():
            return []
        return sorted(str(path.relative_to(management)) for path in management.rglob("*"))

    @contextmanager
    def _patched_import(self, *extra):
        """Enter the usual environment patches plus test-specific ones."""
        with ExitStack() as stack:
            stack.enter_context(mock.patch("photo_manager.importer.load_config", return_value=self.config))
            stack.enter_context(mock.patch("photo_manager.importer.validate_volume"))
            stack.enter_context(mock.patch("photo_manager.importer.ensure_exiftool"))
            stack.enter_context(mock.patch("photo_manager.importer._build_plans", return_value=((self.plan,), 0, 0)))
            for patcher in extra:
                stack.enter_context(patcher)
            yield

    def _assert_preflight_changed_nothing(self, ledger, ledger_bytes, stale):
        self.assertEqual(ledger.read_bytes(), ledger_bytes)
        self.assertEqual(stale.read_bytes(), b"stale")
        self.assertEqual(self._management_entries(), ["checksums.tsv", "tmp", "tmp/20260101_000000_OLD.JPG.part"])
        self.assertFalse((self.destination / "_photo-manager" / "import.lock").exists())
        self.assertFalse(self.plan.destination.exists())

    def test_hard_link_failure_aborts_before_repair_cleanup_and_lock(self):
        ledger, stale = self._seed_management_state()
        ledger_bytes = ledger.read_bytes()
        with self._patched_import(mock.patch("photo_manager.volumes.os.link", side_effect=OSError("unsupported"))), \
             mock.patch("photo_manager.volumes.eject_volume") as eject:
            status = main("import", [], log_dir=self.root / "logs")
        self.assertEqual(status, 2)
        self._assert_preflight_changed_nothing(ledger, ledger_bytes, stale)
        eject.assert_not_called()

    def test_insufficient_space_aborts_before_repair_cleanup_and_lock(self):
        ledger, stale = self._seed_management_state()
        ledger_bytes = ledger.read_bytes()
        empty = SimpleNamespace(total=1, used=1, free=0)
        with self._patched_import(mock.patch("photo_manager.volumes.shutil.disk_usage", return_value=empty)), \
             mock.patch("photo_manager.volumes.eject_volume") as eject:
            status = main("import", [], log_dir=self.root / "logs")
        self.assertEqual(status, 2)
        self._assert_preflight_changed_nothing(ledger, ledger_bytes, stale)
        eject.assert_not_called()

    def test_space_lost_after_the_preflight_is_an_operation_failure(self):
        ledger, stale = self._seed_management_state()
        free = [10 ** 9, 0]

        def disk_usage(_path):
            return SimpleNamespace(total=10 ** 9, used=0, free=free.pop(0) if free else 0)

        with self._patched_import(mock.patch("photo_manager.volumes.shutil.disk_usage", side_effect=disk_usage)), \
             mock.patch("photo_manager.volumes.eject_volume") as eject:
            status = main("import", [], log_dir=self.root / "logs")
        self.assertEqual(status, 1)
        # The abort happened after locking, so the permanent lock file and the
        # repaired ledger are allowed; data and new records are not.
        self.assertTrue((self.destination / "_photo-manager" / "import.lock").is_file())
        self.assertFalse(self.plan.destination.exists())
        self.assertNotIn("DSC00001", ledger.read_text(encoding="utf-8"))
        self.assertFalse(stale.exists())  # cleanup of tool-owned parts is permitted
        eject.assert_not_called()

    def _interrupting_open(self, interrupt_path, readers):
        """Patch target that acts as if SIGINT arrived while reading a file."""
        original_open = Path.open

        class InterruptingReader:
            def __init__(self, handle):
                self.handle = handle
                self.reads = 0

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()
                return False

            def read(self, size):
                self.reads += 1
                if self.reads > 1:
                    raise RunInterrupted("received SIGINT")
                return self.handle.read(size)

        def interrupting_open(path, *args, **kwargs):
            handle = original_open(path, *args, **kwargs)
            if path == interrupt_path:
                reader = InterruptingReader(handle)
                readers.append(reader)
                return reader
            return handle

        return interrupting_open

    def _second_plan(self):
        path = self.source.parent / "DSC00002.JPG"
        path.write_bytes(b"second bytes")
        status = path.stat()
        source_file = SourceFile(path, SourceKind.STILL, status.st_size, status.st_mtime)
        capture = CaptureTime(datetime(2026, 8, 22, 10, 0, 1), "test")
        relative = Path("Camera/2026/2026-08/20260822_100001_DSC00002.JPG")
        return TransferPlan(source_file, capture, self.destination / relative, relative, PlannedAction.COPY, False)

    def _assert_no_partial_archive_state(self, plans):
        for plan in plans:
            self.assertFalse(plan.destination.exists())
        tmp = self.destination / "_photo-manager" / "tmp"
        self.assertEqual(sorted(item.name for item in tmp.iterdir()) if tmp.exists() else [], [])
        ledger = self.destination / "_photo-manager" / "checksums.tsv"
        self.assertNotIn("DSC0000", ledger.read_text(encoding="utf-8") if ledger.exists() else "")

    def test_interrupt_during_copy_stops_the_run_before_the_next_file(self):
        second = self._second_plan()
        readers = []
        resources = RunResources(self.logger)
        with mock.patch("photo_manager.importer.load_config", return_value=self.config), \
             mock.patch("photo_manager.importer.validate_volume"), \
             mock.patch("photo_manager.importer.ensure_exiftool"), \
             mock.patch("photo_manager.importer._build_plans", return_value=((self.plan, second), 0, 0)), \
             mock.patch("photo_manager.volumes.eject_volume") as eject, \
             mock.patch.object(Path, "open", self._interrupting_open(self.plan.source.path, readers)):
            with self.assertRaises(RunInterrupted):
                import_handler(self.args, resources, self.logger)
        self.assertEqual(len(readers), 1)
        eject.assert_not_called()
        resources.cleanup()
        self._assert_no_partial_archive_state((self.plan, second))
        self.assertEqual(self.source.read_bytes(), b"source bytes")
        self.assertEqual(second.source.path.read_bytes(), b"second bytes")
        # The archive lock is only re-acquirable once cleanup released it.
        release = RunResources(self.logger)
        acquire_lock(self.destination, exclusive=True, resources=release)
        release.cleanup()

    def test_cli_reports_an_interrupted_import_as_exit_status_one(self):
        second = self._second_plan()
        readers = []
        with mock.patch("photo_manager.importer.load_config", return_value=self.config), \
             mock.patch("photo_manager.importer.validate_volume"), \
             mock.patch("photo_manager.importer.ensure_exiftool"), \
             mock.patch("photo_manager.importer._build_plans", return_value=((self.plan, second), 0, 0)), \
             mock.patch("photo_manager.volumes.eject_volume") as eject, \
             mock.patch.object(Path, "open", self._interrupting_open(self.plan.source.path, readers)):
            status = main("import", [], log_dir=self.root / "logs")
        self.assertEqual(status, 1)
        eject.assert_not_called()
        self._assert_no_partial_archive_state((self.plan, second))
        release = RunResources(self.logger)
        acquire_lock(self.destination, exclusive=True, resources=release)
        release.cleanup()


class PreflightProbeTests(unittest.TestCase):
    """The write and hard-link probes run before the archive lock exists."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_write_probe_creation_failure_leaves_nothing_behind(self):
        with mock.patch("photo_manager.volumes.os.open", side_effect=OSError("read-only")):
            with self.assertRaises(UsageError):
                ensure_writable(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_write_probe_is_removed_when_the_run_is_interrupted(self):
        with mock.patch("photo_manager.volumes.os.close", side_effect=RunInterrupted("received SIGINT")):
            with self.assertRaises(RunInterrupted):
                ensure_writable(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_write_probe_cleanup_failure_is_reported_as_a_usage_error(self):
        with mock.patch.object(Path, "unlink", side_effect=OSError("busy")):
            with self.assertRaises(UsageError):
                ensure_writable(self.root)

    def test_hard_link_probe_file_creation_failure_removes_new_directories(self):
        with mock.patch("photo_manager.volumes.os.open", side_effect=OSError("no space")):
            with self.assertRaises(UsageError):
                ensure_hard_links(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_hard_link_probe_interruption_removes_probe_files_and_directories(self):
        with mock.patch("photo_manager.volumes.os.link", side_effect=RunInterrupted("received SIGINT")):
            with self.assertRaises(RunInterrupted):
                ensure_hard_links(self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_hard_link_probe_never_removes_an_existing_management_directory(self):
        management = self.root / "_photo-manager"
        management.mkdir()
        (management / "import.lock").write_bytes(b"")
        with mock.patch("photo_manager.volumes.os.link", side_effect=OSError("unsupported")):
            with self.assertRaises(UsageError):
                ensure_hard_links(self.root)
        self.assertTrue((management / "import.lock").is_file())
        # Only the tmp directory the probe itself created is removed.
        self.assertFalse((management / "tmp").exists())


class FinalRecheckTests(unittest.TestCase):
    """F3-a: what the eject decision may reuse, and what it must re-read."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.content = b"verified camera bytes"
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.card = self.root / "card" / "DSC00001.JPG"
        self.card.parent.mkdir(parents=True)
        self.card.write_bytes(self.content)
        self.archive = self.root / "archive"
        self.relative = Path("Camera/2026/2026-08/20260822_100000_DSC00001.JPG")
        self.destination = self.archive / self.relative
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(self.content)
        self.capture = datetime(2026, 8, 22, 10, 0, 0)
        self.logger = logging.getLogger("test-import-recheck")
        self.logger.handlers[:] = [logging.NullHandler()]
        self.hashed = []

    def counting_sha256(self):
        original = naming.sha256_file

        def counted(path, **kwargs):
            self.hashed.append(Path(path))
            return original(path, **kwargs)

        return mock.patch("photo_manager.naming.sha256_file", counted)

    def result(self, digest=None):
        source = SourceFile(self.card, SourceKind.STILL, len(self.content), self.card.stat().st_mtime)
        plan = TransferPlan(source, CaptureTime(self.capture, "test"), self.destination, self.relative,
                            PlannedAction.COPY, False)
        return VerifiedTransfer(plan, digest if digest is not None else self.digest)

    def ledger(self, digest=None, size=None):
        record = make_record(self.relative.as_posix(), digest if digest is not None else self.digest,
                             len(self.content) if size is None else size, self.capture)
        return {record.path: record}

    def verify(self, results, ledger, cache):
        with self.counting_sha256():
            return _verify_records(self.archive, results, ledger, cache, self.logger)

    def remembering_cache(self):
        """A cache in the state a completed copy or skip leaves behind."""
        cache = DigestCache()
        cache.remember(self.card, self.digest)
        return cache

    def test_destination_is_rehashed_and_an_unchanged_source_is_not(self):
        self.assertTrue(self.verify([self.result()], self.ledger(), self.remembering_cache()))
        self.assertEqual(self.hashed, [self.destination])

    def test_source_without_a_remembered_digest_is_hashed_again(self):
        self.assertTrue(self.verify([self.result()], self.ledger(), DigestCache()))
        self.assertEqual(sorted(self.hashed), sorted([self.destination, self.card]))

    def test_changed_source_is_hashed_again_and_a_mismatch_blocks_the_eject(self):
        cache = self.remembering_cache()
        self.card.write_bytes(b"card was swapped!!!!!")
        stamp = self.card.stat().st_mtime + 10
        os.utime(str(self.card), (stamp, stamp))
        self.assertFalse(self.verify([self.result()], self.ledger(), cache))
        self.assertIn(self.card, self.hashed)

    def test_a_changed_source_that_still_matches_is_accepted(self):
        cache = self.remembering_cache()
        stamp = self.card.stat().st_mtime + 10
        os.utime(str(self.card), (stamp, stamp))
        self.assertTrue(self.verify([self.result()], self.ledger(), cache))
        self.assertIn(self.card, self.hashed)

    def test_destination_changed_after_recording_blocks_the_eject(self):
        cache = self.remembering_cache()
        # Same size, different bytes: only the final re-read can catch this.
        self.destination.write_bytes(b"tampered camera bytes")
        self.assertFalse(self.verify([self.result()], self.ledger(), cache))
        self.assertIn(self.destination, self.hashed)

    def test_destination_of_the_wrong_size_blocks_the_eject(self):
        self.destination.write_bytes(self.content + b"!")
        self.assertFalse(self.verify([self.result()], self.ledger(), self.remembering_cache()))

    def test_record_disagreeing_with_this_run_blocks_the_eject(self):
        self.assertFalse(self.verify([self.result()], self.ledger(digest="b" * 64), self.remembering_cache()))

    def test_record_with_a_different_size_blocks_the_eject(self):
        self.assertFalse(self.verify([self.result()], self.ledger(size=len(self.content) + 1),
                                     self.remembering_cache()))

    def test_missing_record_blocks_the_eject(self):
        self.assertFalse(self.verify([self.result()], {}, self.remembering_cache()))
        self.assertEqual(self.hashed, [])


class DuplicateReimportHashingTests(unittest.TestCase):
    """F3-e: planning twice must not hash an unchanged card twice."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.card = self.root / "card"
        self.source = self.card / "DCIM" / "100MSDCF" / "DSC00001.JPG"
        self.source.parent.mkdir(parents=True)
        self.content = b"identical picture bytes"
        self.source.write_bytes(self.content)
        self.stamp = datetime(2026, 8, 22, 10, 0, 0).timestamp()
        os.utime(str(self.source), (self.stamp, self.stamp))
        self.destination = self.root / "archive"
        self.relative = "Camera/2026/2026-08/20260822_100000_DSC00001.JPG"
        self.archived = self.destination / self.relative
        self.archived.parent.mkdir(parents=True)
        self.archived.write_bytes(self.content)
        append_record(self.destination, make_record(self.relative, hashlib.sha256(self.content).hexdigest(),
                                                    len(self.content), datetime(2026, 8, 22, 10, 0, 0)))
        self.config = Config(ArchiveVolume(self.destination, "archive-uuid"), self.card, None,
                             Path("/usr/bin/exiftool"), "sha256", 1.0, True)
        self.args = SimpleNamespace(config=None, dry_run=False, source=None, dest=None, dest_volume_uuid=None,
                                    no_eject=False)
        self.logger = logging.getLogger("test-import-duplicate")
        self.logger.handlers[:] = [logging.NullHandler()]
        self.hashed = []

    def _run(self, *extra):
        original = naming.sha256_file

        def counted(path, **kwargs):
            self.hashed.append(Path(path))
            return original(path, **kwargs)

        resources = RunResources(self.logger)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("photo_manager.importer.load_config", return_value=self.config))
            stack.enter_context(mock.patch("photo_manager.importer.validate_volume"))
            stack.enter_context(mock.patch("photo_manager.importer.ensure_exiftool"))
            # No exiftool tags, so the documented mtime fallback names the file.
            stack.enter_context(mock.patch("photo_manager.metadata.read_exiftool_json", return_value={}))
            stack.enter_context(mock.patch("photo_manager.naming.sha256_file", counted))
            eject = stack.enter_context(mock.patch("photo_manager.volumes.eject_volume"))
            for patcher in extra:
                stack.enter_context(patcher)
            status = import_handler(self.args, resources, self.logger)
        resources.cleanup()
        return status, eject

    def test_unchanged_duplicate_is_hashed_once_per_side_plus_the_final_recheck(self):
        status, eject = self._run()
        self.assertEqual(status, 0)
        # Provisional plan: source then archive.  Authoritative plan: both
        # unchanged, so nothing is read again.  Final recheck: the archive
        # file is always hashed again, the unchanged source never is.
        self.assertEqual(self.hashed, [self.source, self.archived, self.archived])
        eject.assert_called_once_with(self.card)
        self.assertEqual(self.source.read_bytes(), self.content)

    def test_card_changed_before_the_lock_is_replanned_and_not_skipped(self):
        def changed_lock(root, **kwargs):
            # Same name (mtime restored), different bytes: the authoritative
            # pass must see a conflict rather than reuse the provisional skip.
            self.source.write_bytes(b"a completely different picture")
            os.utime(str(self.source), (self.stamp, self.stamp))
            return acquire_lock(root, **kwargs)

        status, eject = self._run(mock.patch("photo_manager.importer.acquire_lock", changed_lock))
        self.assertEqual(status, 0)
        preserved = self.destination / self.relative
        self.assertEqual(preserved.read_bytes(), self.content)
        copy = preserved.with_name("20260822_100000_DSC00001_2.JPG")
        self.assertEqual(copy.read_bytes(), b"a completely different picture")
        eject.assert_called_once_with(self.card)
