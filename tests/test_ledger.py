import hashlib
import logging
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager.config import ArchiveVolume, Config
from photo_manager.ledger import (LedgerError, append_record, ledger_path, load_ledger, make_record, replace_ledger,
                                  supplement_record)
from photo_manager.runtime import RunInterrupted, RunResources
from photo_manager.verify import verify_handler


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "archive"
        self.logs = Path(self.temporary.name) / "logs"
        self.root.mkdir()
        self.capture = datetime(2026, 8, 18, 19, 29, 25)
        self.imported = datetime(2026, 8, 19, 1, 2, 3, tzinfo=timezone(timedelta(hours=9)))

    def record(self, path="Camera/2026/2026-08/x.JPG", digest="a" * 64, size=5):
        return make_record(path, digest, size, self.capture, self.imported)

    def test_append_and_reload_is_headerless_and_durable_shape(self):
        self.assertTrue(append_record(self.root, self.record()))
        raw = ledger_path(self.root).read_text(encoding="utf-8")
        self.assertEqual(raw, "Camera/2026/2026-08/x.JPG\tsha256\t" + "a" * 64 + "\t5\t2026-08-18T19:29:25\t2026-08-19T01:02:03+09:00\n")
        self.assertEqual(load_ledger(self.root)[self.record().path], self.record())
        self.assertFalse(append_record(self.root, self.record()))

    def test_csv_escapes_tab_newline_and_unicode_paths(self):
        record = self.record("Camera/2026/2026-08/日本語\tline\nnext.JPG")
        append_record(self.root, record)
        self.assertEqual(load_ledger(self.root), {record.path: record})

    def test_rejects_invalid_rows_duplicate_and_unsafe_paths(self):
        invalids = [
            "only\ttwo\n",
            "Camera/a\tsha256\t" + "x" * 64 + "\t1\t2026-01-01T00:00:00\t2026-01-01T00:00:00+00:00\n",
            "../Camera/a\tsha256\t" + "a" * 64 + "\t1\t2026-01-01T00:00:00\t2026-01-01T00:00:00+00:00\n",
            "_photo-manager/x\tsha256\t" + "a" * 64 + "\t1\t2026-01-01T00:00:00\t2026-01-01T00:00:00+00:00\n",
            "Camera/a\tsha256\t" + "a" * 64 + "\t-1\t2026-01-01T00:00:00\t2026-01-01T00:00:00+00:00\n",
        ]
        path = ledger_path(self.root)
        path.parent.mkdir()
        for raw in invalids:
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(LedgerError):
                load_ledger(self.root)
        good = self.record().fields()
        path.write_text("\t".join(good) + "\n" + "\t".join(good) + "\n", encoding="utf-8")
        with self.assertRaises(LedgerError):
            load_ledger(self.root)

    def test_only_unterminated_bad_tail_repairs_after_backup(self):
        path = ledger_path(self.root)
        path.parent.mkdir()
        valid = "\t".join(self.record().fields()) + "\n"
        original = valid + "incomplete\trow"
        path.write_text(original, encoding="utf-8")
        records = load_ledger(self.root, repair_tail=True, log_dir=self.logs)
        self.assertEqual(records, {self.record().path: self.record()})
        self.assertEqual(path.read_text(encoding="utf-8"), valid)
        backups = list(self.logs.glob("checksums.tsv.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), original)

    def test_bad_middle_or_newline_terminated_tail_is_not_changed(self):
        path = ledger_path(self.root)
        path.parent.mkdir()
        valid = "\t".join(self.record().fields()) + "\n"
        for raw in ("bad\trow\n" + valid, valid + "bad\trow\n"):
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(LedgerError):
                load_ledger(self.root, repair_tail=True, log_dir=self.logs)
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_backup_failure_never_changes_ledger(self):
        path = ledger_path(self.root)
        path.parent.mkdir()
        original = "\t".join(self.record().fields()) + "\ntruncated"
        path.write_text(original, encoding="utf-8")
        with mock.patch("photo_manager.ledger._backup_original", side_effect=LedgerError("backup unavailable")):
            with self.assertRaises(LedgerError):
                load_ledger(self.root, repair_tail=True, log_dir=self.logs)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_known_view_replaces_the_reread_without_changing_the_outcome(self):
        known = {}
        with mock.patch("photo_manager.ledger.load_ledger", side_effect=AssertionError("ledger was re-read")):
            self.assertTrue(append_record(self.root, self.record(), known=known))
            # The caller's view is updated in place, so the next call sees it.
            self.assertEqual(known, {self.record().path: self.record()})
            self.assertFalse(append_record(self.root, self.record(), known=known))
        self.assertEqual(load_ledger(self.root), {self.record().path: self.record()})
        self.assertEqual(ledger_path(self.root).read_text(encoding="utf-8").count("\n"), 1)

    def test_known_view_still_refuses_a_different_record_for_the_same_path(self):
        known = {}
        append_record(self.root, self.record(), known=known)
        with self.assertRaises(LedgerError):
            append_record(self.root, self.record(digest="b" * 64), known=known)
        self.assertEqual(load_ledger(self.root), {self.record().path: self.record()})

    def test_known_view_accepts_the_same_data_reimported_at_another_time(self):
        known = {}
        append_record(self.root, self.record(), known=known)
        later = make_record(self.record().path, "a" * 64, 5, self.capture,
                            self.imported + timedelta(hours=1))
        self.assertFalse(append_record(self.root, later, known=known))
        self.assertEqual(load_ledger(self.root), {self.record().path: self.record()})

    def test_without_a_known_view_the_ledger_is_still_reread(self):
        reads = []
        original = load_ledger

        def counted(root, **kwargs):
            reads.append(root)
            return original(root, **kwargs)

        with mock.patch("photo_manager.ledger.load_ledger", counted):
            append_record(self.root, self.record())
        self.assertEqual(len(reads), 1)

    def test_supplement_updates_and_uses_the_known_view(self):
        source = Path(self.temporary.name) / "sd-card.JPG"
        source.write_bytes(b"safe data")
        final = self.root / "Camera/2026/2026-08/x.JPG"
        final.parent.mkdir(parents=True)
        final.write_bytes(b"safe data")
        known = {}
        with mock.patch("photo_manager.ledger.load_ledger", side_effect=AssertionError("ledger was re-read")):
            self.assertTrue(supplement_record(self.root, relative_path="Camera/2026/2026-08/x.JPG",
                                              source_path=source, captured_at=self.capture,
                                              imported_at=self.imported, known=known))
            self.assertFalse(supplement_record(self.root, relative_path="Camera/2026/2026-08/x.JPG",
                                               source_path=source, captured_at=self.capture,
                                               imported_at=self.imported, known=known))
        self.assertEqual(list(known), ["Camera/2026/2026-08/x.JPG"])
        self.assertEqual(load_ledger(self.root), known)

    def test_supplement_requires_matching_source_and_destination(self):
        source = Path(self.temporary.name) / "sd-card.JPG"
        source.write_bytes(b"safe data")
        final = self.root / "Camera/2026/2026-08/x.JPG"
        final.parent.mkdir(parents=True)
        final.write_bytes(b"safe data")
        self.assertTrue(supplement_record(self.root, relative_path="Camera/2026/2026-08/x.JPG", source_path=source, captured_at=self.capture, imported_at=self.imported))
        self.assertFalse(supplement_record(self.root, relative_path="Camera/2026/2026-08/x.JPG", source_path=source, captured_at=self.capture, imported_at=self.imported))
        self.assertEqual(source.read_bytes(), b"safe data")

    def test_supplement_mismatch_does_not_add_record_or_change_source(self):
        source = Path(self.temporary.name) / "sd-card.JPG"
        source.write_bytes(b"card")
        final = self.root / "Camera/2026/2026-08/x.JPG"
        final.parent.mkdir(parents=True)
        final.write_bytes(b"disk")
        with self.assertRaises(LedgerError):
            supplement_record(self.root, relative_path="Camera/2026/2026-08/x.JPG", source_path=source, captured_at=self.capture)
        self.assertEqual(load_ledger(self.root), {})
        self.assertEqual(source.read_bytes(), b"card")


class ManagedTemporaryRecoveryTests(unittest.TestCase):
    """F4: a leftover checksums.tsv.*.part must never block recovery forever."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "archive"
        self.logs = Path(self.temporary.name) / "logs"
        self.root.mkdir()
        self.capture = datetime(2026, 8, 18, 19, 29, 25)
        self.imported = datetime(2026, 8, 19, 1, 2, 3, tzinfo=timezone(timedelta(hours=9)))
        self.path = ledger_path(self.root)
        self.path.parent.mkdir()
        self.repair_part = self.path.with_name(self.path.name + ".repair.part")
        self.mirror_part = self.path.with_name(self.path.name + ".mirror.part")

    def record(self, path="Camera/2026/2026-08/x.JPG", digest="a" * 64, size=5):
        return make_record(path, digest, size, self.capture, self.imported)

    def valid_row(self):
        return "\t".join(self.record().fields()) + "\n"

    def write_broken_tail(self):
        raw = self.valid_row() + "incomplete\trow"
        self.path.write_text(raw, encoding="utf-8")
        return raw

    def test_interrupted_repair_write_leaves_no_repair_temporary(self):
        raw = self.write_broken_tail()
        with mock.patch("photo_manager.ledger._serialize", side_effect=RunInterrupted("received SIGINT")):
            with self.assertRaises(RunInterrupted):
                load_ledger(self.root, repair_tail=True, log_dir=self.logs)
        self.assertFalse(self.repair_part.exists())
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_interrupted_mirror_write_leaves_no_mirror_temporary(self):
        for error in (RunInterrupted("received SIGTERM"), KeyboardInterrupt()):
            with mock.patch("photo_manager.ledger._serialize", side_effect=error):
                with self.assertRaises(type(error)):
                    replace_ledger(self.root, [self.record()])
            self.assertFalse(self.mirror_part.exists())
            self.assertFalse(self.path.exists())

    def test_stale_repair_temporary_is_refused_by_default_and_cleared_when_locked(self):
        raw = self.write_broken_tail()
        self.repair_part.write_bytes(b"leftover from an interrupted repair")
        with self.assertRaises(LedgerError):
            load_ledger(self.root, repair_tail=True, log_dir=self.logs)
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)
        self.assertEqual(self.repair_part.read_bytes(), b"leftover from an interrupted repair")
        with self.assertLogs("photo_manager.ledger", level="WARNING") as captured:
            records = load_ledger(self.root, repair_tail=True, log_dir=self.logs, allow_stale_temporary=True)
        self.assertEqual(records, {self.record().path: self.record()})
        self.assertEqual(self.path.read_text(encoding="utf-8"), self.valid_row())
        self.assertFalse(self.repair_part.exists())
        self.assertTrue(any("Removed stale managed ledger temporary" in line for line in captured.output))

    def test_stale_mirror_temporary_is_refused_by_default_and_cleared_when_locked(self):
        self.mirror_part.write_bytes(b"leftover from an interrupted mirror")
        with self.assertRaises(LedgerError):
            replace_ledger(self.root, [self.record()])
        self.assertEqual(self.mirror_part.read_bytes(), b"leftover from an interrupted mirror")
        self.assertFalse(self.path.exists())
        with self.assertLogs("photo_manager.ledger", level="WARNING") as captured:
            replace_ledger(self.root, [self.record()], allow_stale_temporary=True)
        self.assertFalse(self.mirror_part.exists())
        self.assertEqual(load_ledger(self.root), {self.record().path: self.record()})
        self.assertTrue(any("Removed stale managed ledger temporary" in line for line in captured.output))

    def test_directory_in_place_of_temporary_is_never_removed(self):
        self.mirror_part.mkdir()
        with self.assertRaises(LedgerError):
            replace_ledger(self.root, [self.record()], allow_stale_temporary=True)
        self.assertTrue(self.mirror_part.is_dir())
        self.assertFalse(self.path.exists())

    def test_failure_at_replace_keeps_the_temporary(self):
        with mock.patch("photo_manager.ledger.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(LedgerError):
                replace_ledger(self.root, [self.record()])
        self.assertTrue(self.mirror_part.exists())
        self.assertFalse(self.path.exists())

    def test_failure_at_repair_replace_keeps_the_temporary(self):
        raw = self.write_broken_tail()
        with mock.patch("photo_manager.ledger.os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaises(LedgerError):
                load_ledger(self.root, repair_tail=True, log_dir=self.logs, allow_stale_temporary=True)
        self.assertTrue(self.repair_part.exists())
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)

    def test_verify_never_clears_leftovers_or_changes_the_ledger(self):
        content = b"photo"
        relative = "Camera/2026/2026-08/photo.JPG"
        data_file = self.root / relative
        data_file.parent.mkdir(parents=True)
        data_file.write_bytes(content)
        append_record(self.root, make_record(relative, hashlib.sha256(content).hexdigest(), len(content), self.capture, self.imported))
        self.repair_part.write_bytes(b"leftover repair")
        self.mirror_part.write_bytes(b"leftover mirror")
        before = self.path.read_bytes()
        config = Config(ArchiveVolume(self.root, "archive-uuid"), None, None, Path("/usr/bin/exiftool"), "sha256", 1.0, True)
        logger = logging.getLogger("test-ledger-verify")
        logger.handlers[:] = [logging.NullHandler()]
        args = SimpleNamespace(config=None, dest=None, dest_volume_uuid=None, year=None, month=None)
        resources = RunResources(logger)
        with mock.patch("photo_manager.verify.load_config", return_value=config), \
             mock.patch("photo_manager.verify.validate_volume"):
            result = verify_handler(args, resources, logger)
        resources.cleanup()
        self.assertEqual(result, 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.repair_part.read_bytes(), b"leftover repair")
        self.assertEqual(self.mirror_part.read_bytes(), b"leftover mirror")
