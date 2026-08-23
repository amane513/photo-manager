import hashlib
import logging
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager import mirror as mirror_module
from photo_manager.config import ArchiveVolume, Config
from photo_manager.ledger import LedgerError, load_ledger, make_record, replace_ledger
from photo_manager.locking import acquire_mirror_locks
from photo_manager.mirror import mirror_handler
from photo_manager.runtime import RunInterrupted, RunResources
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

    def _run(self, dry_run=False, *extra):
        args = SimpleNamespace(config=None, dry_run=dry_run)
        resources = RunResources(self.logger)
        infos = [VolumeInfo(self.source, "source-uuid", "disk1s1", "disk1"),
                 VolumeInfo(self.target, "target-uuid", "disk2s1", "disk2")]
        with ExitStack() as stack:
            stack.enter_context(mock.patch("photo_manager.mirror.load_config", return_value=self.config))
            stack.enter_context(mock.patch("photo_manager.mirror.validate_volume", side_effect=infos))
            for patcher in extra:
                stack.enter_context(patcher)
            try:
                return mirror_handler(args, resources, self.logger)
            finally:
                resources.cleanup()

    def _counting_hash(self, hashed):
        """Patch that records every file mirror actually reads for a digest."""
        original = mirror_module._hash

        def counted(path):
            hashed.append(Path(path))
            return original(path)

        return mock.patch("photo_manager.mirror._hash", counted)

    def test_empty_target_is_copied_and_ledger_is_snapshot(self):
        self.assertEqual(self._run(), 0)
        target_file = self.target / self.relative
        self.assertEqual(target_file.read_bytes(), self.source_file.read_bytes())
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))

    def test_bad_source_does_not_change_target(self):
        # The specification's order is check paths -> lock both volumes ->
        # verify the whole source, so the mirror's lock file may exist by the
        # time the corruption is found.  No mirror *data* and no published
        # ledger may be created by such a run.
        self.source_file.write_bytes(b"corrupted after import")
        self.assertEqual(self._run(), 1)
        self.assertFalse((self.target / self.relative).exists())
        self.assertFalse((self.target / "Camera").exists())
        self.assertFalse((self.target / "_photo-manager" / "checksums.tsv").exists())

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

    def test_stale_ledger_temporary_is_recovered_by_the_locked_mirror(self):
        management = self.target / "_photo-manager"
        management.mkdir()
        stale = management / "checksums.tsv.mirror.part"
        stale.write_bytes(b"leftover from an interrupted mirror")
        self.assertEqual(self._run(), 0)
        self.assertFalse(stale.exists())
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))

    def test_interrupted_ledger_publish_leaves_no_managed_temporary(self):
        with mock.patch("photo_manager.ledger._serialize", side_effect=RunInterrupted("received SIGINT")):
            with self.assertRaises(RunInterrupted):
                self._run()
        management = self.target / "_photo-manager"
        self.assertFalse((management / "checksums.tsv.mirror.part").exists())
        self.assertFalse((management / "checksums.tsv").exists())
        self.assertEqual(self._run(), 0)
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))

    def _lock_watcher(self, hashed, marks):
        """Patch that records what had been hashed when the locks were taken."""
        def locking(pairs, resources):
            marks.append(list(hashed))
            return acquire_mirror_locks(pairs, resources)

        return mock.patch("photo_manager.mirror.acquire_mirror_locks", locking)

    def test_source_is_verified_once_and_only_after_the_locks_are_held(self):
        hashed, marks = [], []
        with self._counting_hash(hashed):
            self.assertEqual(self._run(False, self._lock_watcher(hashed, marks)), 0)
        self.assertEqual([path for path in marks[0] if path == self.source_file], [])
        self.assertEqual([path for path in hashed if path == self.source_file], [self.source_file])

    def test_dry_run_still_verifies_the_whole_source(self):
        hashed = []
        with self._counting_hash(hashed):
            self.assertEqual(self._run(True), 0)
        self.assertEqual([path for path in hashed if path == self.source_file], [self.source_file])
        self.assertFalse((self.target / self.relative).exists())

    def test_target_is_verified_once_before_and_once_after_publishing_the_ledger(self):
        hashed = []
        published = []
        real_replace = mirror_module.replace_ledger

        def replacing(root, records, **kwargs):
            published.append(list(hashed))
            return real_replace(root, records, **kwargs)

        with self._counting_hash(hashed):
            self.assertEqual(self._run(False, mock.patch("photo_manager.mirror.replace_ledger", replacing)), 0)
        target_file = self.target / self.relative
        before = [path for path in published[0] if path == target_file]
        after = [path for path in hashed if path == target_file]
        self.assertEqual(len(before), 1)  # step 7, before the ledger is published
        self.assertEqual(len(after), 2)   # plus step 8, after it is published

    def test_conflict_appearing_before_the_lock_is_found_and_stops_the_mirror(self):
        def conflicting(pairs, resources):
            target_file = self.target / self.relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(b"appeared between the passes")
            return acquire_mirror_locks(pairs, resources)

        self.assertEqual(self._run(False, mock.patch("photo_manager.mirror.acquire_mirror_locks", conflicting)), 1)
        self.assertEqual((self.target / self.relative).read_bytes(), b"appeared between the passes")
        self.assertFalse((self.target / "_photo-manager" / "checksums.tsv").exists())

    def test_extra_appearing_before_the_lock_is_reported_and_retained(self):
        extra = self.target / "Camera/2025/2025-01/late.JPG"

        def creating(pairs, resources):
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_bytes(b"keep")
            return acquire_mirror_locks(pairs, resources)

        with self.assertLogs("test_mirror", level="WARNING") as captured:
            self.assertEqual(self._run(False, mock.patch("photo_manager.mirror.acquire_mirror_locks", creating)), 0)
        self.assertEqual(extra.read_bytes(), b"keep")
        retained = [line for line in captured.output if "late.JPG" in line and "retained" in line]
        self.assertEqual(len(retained), 1)

    def test_successful_mirror_hashes_each_file_exactly_as_required(self):
        hashed = []
        with self._counting_hash(hashed):
            self.assertEqual(self._run(), 0)
        target_file = self.target / self.relative
        # One post-lock source verification (step 3) and the two target
        # verifications the specification's steps 7 and 8 each require.  The
        # copy's own read-back check is done inside transfer, not here.
        self.assertEqual(hashed, [self.source_file, target_file, target_file])

    def test_already_mirrored_file_is_not_hashed_more_than_the_passes_need(self):
        self.assertEqual(self._run(), 0)
        hashed = []
        with self._counting_hash(hashed):
            self.assertEqual(self._run(), 0)
        target_file = self.target / self.relative
        # Provisional conflict check, post-lock conflict check, step 7, step 8.
        self.assertEqual(hashed.count(target_file), 4)
        # And the source is still verified exactly once, after the locks.
        self.assertEqual(hashed.count(self.source_file), 1)

    def test_plan_is_recomputed_after_the_lock_so_a_new_source_file_is_mirrored(self):
        late_relative = "Camera/2026/2026-08/20260822_130000_DSC00002.JPG"
        late = self.source / late_relative

        def appearing(pairs, resources):
            late.parent.mkdir(parents=True, exist_ok=True)
            late.write_bytes(b"arrived between the passes")
            record = make_record(late_relative, hashlib.sha256(late.read_bytes()).hexdigest(),
                                 late.stat().st_size, datetime(2026, 8, 22, 13, tzinfo=timezone.utc))
            replace_ledger(self.source, list(load_ledger(self.source).values()) + [record])
            return acquire_mirror_locks(pairs, resources)

        self.assertEqual(self._run(False, mock.patch("photo_manager.mirror.acquire_mirror_locks", appearing)), 0)
        self.assertEqual((self.target / late_relative).read_bytes(), b"arrived between the passes")
        self.assertEqual(load_ledger(self.target), load_ledger(self.source))

    def test_capacity_is_rechecked_after_the_lock_before_anything_is_copied(self):
        free = [10 ** 9, 0]

        def disk_usage(_path):
            return SimpleNamespace(total=10 ** 9, used=0, free=free.pop(0) if free else 0)

        self.assertEqual(self._run(False, mock.patch("photo_manager.volumes.shutil.disk_usage",
                                                     side_effect=disk_usage)), 1)
        self.assertFalse((self.target / self.relative).exists())
        self.assertFalse((self.target / "Camera").exists())
        self.assertFalse((self.target / "_photo-manager" / "checksums.tsv").exists())
