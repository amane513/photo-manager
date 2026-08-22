import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from photo_manager.discovery import SourceFile, SourceKind
from photo_manager.metadata import CaptureTime
from photo_manager.naming import PlannedAction, build_transfer_plans


class NamingTests(unittest.TestCase):
    def source(self, root, name, contents, kind=SourceKind.STILL):
        path = root / name
        path.write_bytes(contents)
        return SourceFile(path, kind, len(contents), path.stat().st_mtime)

    def captures(self, *sources):
        return {source.path: CaptureTime(datetime(2026, 8, 18, 19, 29, 25), "test") for source in sources}

    def test_paths_keep_original_name_extension_and_pair_adjacency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpg = self.source(root, "DSC00020.JpG", b"jpg")
            arw = self.source(root, "DSC00020.ARW", b"raw")
            mp4 = self.source(root, "C0001.MP4", b"movie", SourceKind.VIDEO)
            xml = self.source(root, "C0001M01.XML", b"xml", SourceKind.SIDECAR_XML)
            plans = build_transfer_plans([xml, mp4, jpg, arw], self.captures(jpg, arw, mp4, xml), root / "archive")
            names = [plan.relative_destination.name for plan in plans]
            self.assertEqual(names, sorted(names))
            self.assertIn("20260818_192925_DSC00020.JpG", names)
            self.assertIn("20260818_192925_DSC00020.ARW", names)
            self.assertIn("20260818_192925_C0001.MP4", names)
            self.assertIn("20260818_192925_C0001M01.XML", names)
            self.assertEqual(plans[0].relative_destination.parts[:3], ("Camera", "2026", "2026-08"))

    def test_months_are_derived_from_each_capture_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.source(root, "A.JPG", b"a")
            second = self.source(root, "B.JPG", b"b")
            captures = {
                first.path: CaptureTime(datetime(2026, 8, 31, 23, 59, 59), "test"),
                second.path: CaptureTime(datetime(2026, 9, 1, 0, 0, 0), "test"),
            }
            plans = build_transfer_plans([first, second], captures, root / "archive")
            self.assertEqual(plans[0].relative_destination.parts[1:3], ("2026", "2026-08"))
            self.assertEqual(plans[1].relative_destination.parts[1:3], ("2026", "2026-09"))

    def test_identical_existing_file_skips_and_reports_missing_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root, "DSC.JPG", b"same")
            target = root / "archive/Camera/2026/2026-08/20260818_192925_DSC.JPG"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"same")
            plan = build_transfer_plans([source], self.captures(source), root / "archive", ledger_paths=[])[0]
            self.assertEqual(plan.action, PlannedAction.SKIP)
            self.assertTrue(plan.ledger_missing)
            self.assertEqual(target.read_bytes(), b"same")

    def test_different_candidates_are_numbered_without_replacing_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root, "DSC.JPG", b"card")
            folder = root / "archive/Camera/2026/2026-08"
            folder.mkdir(parents=True)
            base = folder / "20260818_192925_DSC.JPG"
            second = folder / "20260818_192925_DSC_2.JPG"
            base.write_bytes(b"different")
            second.write_bytes(b"also-different")
            plan = build_transfer_plans([source], self.captures(source), root / "archive")[0]
            self.assertEqual(plan.action, PlannedAction.COPY)
            self.assertEqual(plan.destination.name, "20260818_192925_DSC_3.JPG")
            self.assertEqual(base.read_bytes(), b"different")
            self.assertEqual(second.read_bytes(), b"also-different")

    def test_numbered_identical_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root, "DSC.JPG", b"card")
            folder = root / "archive/Camera/2026/2026-08"
            folder.mkdir(parents=True)
            (folder / "20260818_192925_DSC.JPG").write_bytes(b"different")
            duplicate = folder / "20260818_192925_DSC_2.JPG"
            duplicate.write_bytes(b"card")
            plan = build_transfer_plans([source], self.captures(source), root / "archive")[0]
            self.assertEqual(plan.action, PlannedAction.SKIP)
            self.assertEqual(plan.destination, duplicate)

