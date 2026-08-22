import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

from photo_manager.ledger import LedgerError, append_record, ledger_path, load_ledger, make_record, supplement_record


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
