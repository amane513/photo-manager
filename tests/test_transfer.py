import hashlib
import logging
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from photo_manager.discovery import SourceFile, SourceKind
from photo_manager.metadata import CaptureTime
from photo_manager.naming import build_transfer_plans
from photo_manager.runtime import RunInterrupted, RunResources
from photo_manager import transfer as transfer_module
from photo_manager.transfer import TransferStatus, cleanup_stale_parts, management_tmp_dir, transfer_file


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source_root = self.root / "card"
        self.archive = self.root / "archive"
        self.source_root.mkdir()
        self.resources = RunResources(logging.getLogger("transfer-test"))
        self.addCleanup(self.resources.cleanup)

    def plan(self, name="DSC00001.JPG", content=b"photo"):
        source_path = self.source_root / name
        source_path.write_bytes(content)
        source = SourceFile(source_path, SourceKind.STILL, len(content), source_path.stat().st_mtime)
        capture = CaptureTime(datetime(2026, 8, 18, 19, 29, 25), "test")
        return build_transfer_plans([source], {source.path: capture}, self.archive)[0]

    def test_verified_copy_preserves_source_and_mtime(self):
        plan = self.plan(content=b"safe bytes" * 200)
        original_mtime = 1_700_000_000_123_456_789
        os.utime(plan.source.path, ns=(original_mtime, original_mtime))
        result = transfer_file(plan, self.archive, self.resources, chunk_size=17)
        self.assertEqual(result.status, TransferStatus.COPIED)
        self.assertEqual(plan.source.path.read_bytes(), plan.destination.read_bytes())
        self.assertEqual(result.digest, hashlib.sha256(plan.source.path.read_bytes()).hexdigest())
        self.assertEqual(plan.destination.stat().st_mtime_ns, original_mtime)
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())

    def test_temporary_that_cannot_be_removed_is_a_warning_not_a_failed_copy(self):
        plan = self.plan(content=b"published bytes")
        part = management_tmp_dir(self.archive) / (plan.destination.name + ".part")
        real_unlink = Path.unlink
        synced = []
        real_sync = transfer_module._durable_sync

        def refuse_part(self_path, *args, **kwargs):
            if self_path == part:
                raise OSError(13, "Permission denied")
            return real_unlink(self_path, *args, **kwargs)

        def record_sync(fd, logger, *, what):
            synced.append(what)
            return real_sync(fd, logger, what=what)

        with mock.patch.object(Path, "unlink", refuse_part), \
                mock.patch.object(transfer_module, "_durable_sync", record_sync):
            result = transfer_file(plan, self.archive, self.resources)

        self.assertEqual(result.status, TransferStatus.COPIED)
        self.assertEqual(result.digest, hashlib.sha256(plan.source.path.read_bytes()).hexdigest())
        self.assertEqual(len(result.warnings), 1)
        self.assertIn(str(part), result.warnings[0])
        self.assertIsNone(result.message)
        # The published file is real and durable: its directory was fsynced.
        self.assertEqual(plan.destination.read_bytes(), plan.source.path.read_bytes())
        self.assertIn("destination directory", synced)
        # The temporary stays registered so the run's cleanup retries it.
        self.assertTrue(part.exists())
        self.resources.cleanup()
        self.assertFalse(part.exists())
        self.assertTrue(plan.destination.exists())

    def test_a_failing_link_is_still_a_failure(self):
        plan = self.plan(content=b"never published")

        def refuse_link(*_args, **_kwargs):
            raise OSError(5, "Input/output error")

        with mock.patch.object(os, "link", refuse_link):
            result = transfer_file(plan, self.archive, self.resources)

        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertEqual(result.warnings, ())
        self.assertFalse(plan.destination.exists())
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())

    def test_existing_final_file_is_never_replaced_when_link_races(self):
        plan = self.plan(content=b"card data")
        original_link = os.link

        def race(source, destination):
            Path(destination).write_bytes(b"existing archive data")
            return original_link(source, destination)

        with mock.patch("photo_manager.transfer.os.link", side_effect=race):
            result = transfer_file(plan, self.archive, self.resources)
        self.assertEqual(result.status, TransferStatus.CONFLICT)
        self.assertEqual(plan.destination.read_bytes(), b"existing archive data")
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())
        self.assertEqual(plan.source.path.read_bytes(), b"card data")

    def test_hash_mismatch_removes_only_our_part(self):
        plan = self.plan()
        def bad_hash(fd, *, chunk_size):
            return "0" * 64
        with mock.patch("photo_manager.transfer._hash_fd", side_effect=bad_hash):
            result = transfer_file(plan, self.archive, self.resources)
        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertFalse(plan.destination.exists())
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())
        self.assertEqual(plan.source.path.read_bytes(), b"photo")

    def test_mtime_failure_removes_part_without_touching_source_or_final(self):
        plan = self.plan(content=b"card data")
        with mock.patch("photo_manager.transfer.os.utime", side_effect=OSError("no timestamps")):
            result = transfer_file(plan, self.archive, self.resources)
        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertFalse(plan.destination.exists())
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())
        self.assertEqual(plan.source.path.read_bytes(), b"card data")

    def test_write_failure_removes_part_without_touching_source_or_final(self):
        plan = self.plan(content=b"card data")
        original_write = os.fdopen

        class FailingWriter:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def write(self, _block):
                raise OSError("disk full")

        def fdopen(fd, mode, closefd=True):
            if "w" in mode:
                os.close(fd)
                return FailingWriter()
            return original_write(fd, mode, closefd=closefd)

        with mock.patch("photo_manager.transfer.os.fdopen", side_effect=fdopen):
            result = transfer_file(plan, self.archive, self.resources)
        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertFalse(plan.destination.exists())
        self.assertFalse(management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part").exists())
        self.assertEqual(plan.source.path.read_bytes(), b"card data")

    def test_stale_cleanup_is_limited_to_valid_regular_files_in_management_tmp(self):
        tmp = management_tmp_dir(self.archive)
        tmp.mkdir(parents=True)
        owned = tmp / "20260818_192925_DSC.JPG.part"
        owned.write_bytes(b"partial")
        arbitrary = tmp / "unrelated.part"
        arbitrary.write_bytes(b"keep")
        nested = tmp / "nested"
        nested.mkdir()
        nested_part = nested / "20260818_192925_DSC.JPG.part"
        nested_part.write_bytes(b"keep")
        elsewhere = self.archive / "Camera" / "20260818_192925_DSC.JPG.part"
        elsewhere.parent.mkdir(parents=True)
        elsewhere.write_bytes(b"keep")
        self.assertEqual(cleanup_stale_parts(self.archive), 1)
        self.assertFalse(owned.exists())
        self.assertTrue(arbitrary.exists())
        self.assertTrue(nested_part.exists())
        self.assertTrue(elsewhere.exists())

    def test_source_change_after_copy_fails_without_publishing(self):
        plan = self.plan(content=b"source")
        original_stat = Path.stat
        calls = {"source": 0}
        def changing_stat(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            if path == plan.source.path:
                calls["source"] += 1
                if calls["source"] == 2:
                    # A new stat result without changing any source data.
                    values = list(value)
                    values[8] = value.st_mtime + 1
                    return os.stat_result(values)
            return value
        with mock.patch.object(Path, "stat", changing_stat):
            result = transfer_file(plan, self.archive, self.resources)
        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertFalse(plan.destination.exists())
        self.assertEqual(plan.source.path.read_bytes(), b"source")

    def test_interrupt_during_copy_aborts_instead_of_reporting_a_failed_file(self):
        content = b"card data" * 100
        plan = self.plan(content=content)
        original_open = Path.open
        original_fdopen = os.fdopen
        readers = []
        writers = []

        class InterruptingReader:
            """Read one block, then behave as if SIGINT arrived mid-copy."""

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
            if path == plan.source.path:
                reader = InterruptingReader(handle)
                readers.append(reader)
                return reader
            return handle

        def recording_fdopen(fd, mode, closefd=True):
            handle = original_fdopen(fd, mode, closefd=closefd)
            writers.append(handle)
            return handle

        with mock.patch.object(Path, "open", interrupting_open), \
             mock.patch("photo_manager.transfer.os.fdopen", side_effect=recording_fdopen):
            with self.assertRaises(RunInterrupted):
                transfer_file(plan, self.archive, self.resources, chunk_size=64)
        part = management_tmp_dir(self.archive).joinpath(plan.destination.name + ".part")
        self.assertFalse(plan.destination.exists())
        self.assertTrue(part.exists())
        self.assertTrue(all(reader.handle.closed for reader in readers))
        self.assertTrue(writers and all(handle.closed for handle in writers))
        self.resources.cleanup()
        self.assertFalse(part.exists())
        self.assertFalse(plan.destination.exists())
        self.assertEqual(plan.source.path.read_bytes(), content)
