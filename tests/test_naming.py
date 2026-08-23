import hashlib
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from photo_manager import naming
from photo_manager.discovery import SourceFile, SourceKind
from photo_manager.metadata import CaptureTime
from photo_manager.naming import DigestCache, PlannedAction, build_transfer_plans


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

    def test_months_follow_the_recorded_local_time_across_a_month_boundary(self):
        # 2026-09-01 06:00+09:00 is 2026-08-31 21:00 UTC, and
        # 2026-08-31 22:00-04:00 is 2026-09-01 02:00 UTC.  Both must be filed
        # by their recorded local month, never by their UTC month.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.source(root, "C0001.MP4", b"a", SourceKind.VIDEO)
            second = self.source(root, "C0002.MP4", b"b", SourceKind.VIDEO)
            captures = {
                first.path: CaptureTime(datetime(2026, 9, 1, 6, 0, 0, tzinfo=timezone(timedelta(hours=9))), "test"),
                second.path: CaptureTime(datetime(2026, 8, 31, 22, 0, 0, tzinfo=timezone(-timedelta(hours=4))), "test"),
            }
            plans = build_transfer_plans([first, second], captures, root / "archive")
            self.assertEqual(plans[0].relative_destination.parts[1:3], ("2026", "2026-09"))
            self.assertEqual(plans[0].relative_destination.name, "20260901_060000_C0001.MP4")
            self.assertEqual(plans[1].relative_destination.parts[1:3], ("2026", "2026-08"))
            self.assertEqual(plans[1].relative_destination.name, "20260831_220000_C0002.MP4")

    def test_skipped_plan_carries_the_verified_destination_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root, "DSC.JPG", b"same")
            target = root / "archive/Camera/2026/2026-08/20260818_192925_DSC.JPG"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"same")
            plans = build_transfer_plans([source], self.captures(source), root / "archive")
            self.assertEqual(plans[0].action, PlannedAction.SKIP)
            self.assertEqual(plans[0].verified_digest, hashlib.sha256(b"same").hexdigest())

    def test_copy_plan_has_no_verified_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source(root, "DSC.JPG", b"card")
            plans = build_transfer_plans([source], self.captures(source), root / "archive")
            self.assertEqual(plans[0].action, PlannedAction.COPY)
            self.assertIsNone(plans[0].verified_digest)

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


class DigestCacheTests(unittest.TestCase):
    """A carried-over digest may only remove work, never a comparison."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hashed = []

    def counting_sha256(self):
        """Patch that records every file actually read by ``sha256_file``."""
        original = naming.sha256_file

        def counted(path, **kwargs):
            self.hashed.append(Path(path))
            return original(path, **kwargs)

        return mock.patch("photo_manager.naming.sha256_file", counted)

    def source(self, name, contents):
        path = self.root / name
        path.write_bytes(contents)
        return SourceFile(path, SourceKind.STILL, len(contents), path.stat().st_mtime)

    def destination_for(self, name, contents):
        target = self.root / "archive/Camera/2026/2026-08" / ("20260818_192925_" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        return target

    def captures(self, *sources):
        return {item.path: CaptureTime(datetime(2026, 8, 18, 19, 29, 25), "test") for item in sources}

    def plan_with(self, source, cache):
        return build_transfer_plans([source], self.captures(source), self.root / "archive", digest_cache=cache)[0]

    def rewrite(self, path, contents):
        """Replace contents and move the mtime, as an external writer would."""
        path.write_bytes(contents)
        stamp = path.stat().st_mtime + 10
        os.utime(str(path), (stamp, stamp))

    def test_unchanged_files_are_hashed_once_across_two_planning_passes(self):
        source = self.source("DSC.JPG", b"same")
        target = self.destination_for("DSC.JPG", b"same")
        cache = DigestCache()
        with self.counting_sha256():
            first = self.plan_with(source, cache)
            del self.hashed[:]
            second = self.plan_with(source, cache)
        self.assertEqual(first.action, PlannedAction.SKIP)
        self.assertEqual(second.action, PlannedAction.SKIP)
        self.assertEqual(second.verified_digest, first.verified_digest)
        self.assertEqual(self.hashed, [])
        self.assertEqual(target.read_bytes(), b"same")

    def test_without_a_shared_cache_each_pass_hashes_both_sides(self):
        source = self.source("DSC.JPG", b"same")
        self.destination_for("DSC.JPG", b"same")
        with self.counting_sha256():
            self.plan_with(source, None)
            del self.hashed[:]
            self.plan_with(source, None)
        self.assertEqual(len(self.hashed), 2)

    def test_changed_source_is_hashed_again_and_is_not_skipped(self):
        source = self.source("DSC.JPG", b"same")
        target = self.destination_for("DSC.JPG", b"same")
        cache = DigestCache()
        self.plan_with(source, cache)
        self.rewrite(source.path, b"different but same length")
        changed = SourceFile(source.path, SourceKind.STILL, source.path.stat().st_size, source.path.stat().st_mtime)
        target.write_bytes(b"different but same lengtH")
        with self.counting_sha256():
            plan = self.plan_with(changed, cache)
        self.assertIn(source.path, self.hashed)
        self.assertEqual(plan.action, PlannedAction.COPY)
        self.assertEqual(target.read_bytes(), b"different but same lengtH")

    def test_changed_destination_is_hashed_again_and_is_not_skipped(self):
        source = self.source("DSC.JPG", b"same")
        target = self.destination_for("DSC.JPG", b"same")
        cache = DigestCache()
        self.assertEqual(self.plan_with(source, cache).action, PlannedAction.SKIP)
        self.rewrite(target, b"same but tampered with")
        self.rewrite(source.path, b"same but tampered witH")
        changed = SourceFile(source.path, SourceKind.STILL, source.path.stat().st_size, source.path.stat().st_mtime)
        with self.counting_sha256():
            plan = self.plan_with(changed, cache)
        self.assertIn(target, self.hashed)
        self.assertEqual(plan.action, PlannedAction.COPY)
        self.assertEqual(target.read_bytes(), b"same but tampered with")

    def test_size_or_mtime_change_alone_invalidates_a_remembered_digest(self):
        path = self.root / "file.bin"
        path.write_bytes(b"abcd")
        cache = DigestCache()
        digest = cache.measure(path)
        self.assertEqual(cache.reuse(path), digest)
        stamp = path.stat().st_mtime + 5
        os.utime(str(path), (stamp, stamp))
        self.assertIsNone(cache.reuse(path))
        again = cache.measure(path)
        self.assertEqual(again, digest)
        path.write_bytes(b"abcde")
        self.assertIsNone(cache.reuse(path))
        path.unlink()
        self.assertIsNone(cache.reuse(path))

