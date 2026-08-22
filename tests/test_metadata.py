import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from photo_manager.discovery import SourceFile, SourceKind, discover_files
from photo_manager.metadata import determine_capture_times, read_exiftool_json


def runner_with(rows, code=0):
    def runner(command, **_kwargs):
        return subprocess.CompletedProcess(command, code, json.dumps(rows).encode(), b"failure")
    return runner


class MetadataTests(unittest.TestCase):
    exiftool = Path("/usr/local/bin/exiftool")

    def source(self, path, kind, pair=None, mtime=1_700_000_000):
        path.write_bytes(b"x")
        return SourceFile(path.absolute(), kind, 1, mtime, pair.absolute() if pair else None)

    def test_still_uses_exif_then_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = self.source(root / "DSC1.JPG", SourceKind.STILL)
            b = self.source(root / "DSC2.ARW", SourceKind.STILL)
            rows = [{"SourceFile": str(a.path), "DateTimeOriginal": "2026:08:18 20:22:20"}, {"SourceFile": str(b.path)}]
            result = determine_capture_times([a, b], self.exiftool, runner=runner_with(rows))
            self.assertEqual(result.capture_times[a.path].value, datetime(2026, 8, 18, 20, 22, 20))
            self.assertEqual(result.capture_times[a.path].source, "exif:DateTimeOriginal")
            self.assertEqual(result.capture_times[b.path].source, "mtime")

    def test_xml_wins_and_is_inherited_with_foreign_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml_path = root / "C0001M01.XML"
            xml_path.write_text('<Clip><CreationDate value="2026-08-18T09:10:11-04:00"/></Clip>')
            mp4 = self.source(root / "C0001.MP4", SourceKind.VIDEO, xml_path)
            xml = SourceFile(xml_path.absolute(), SourceKind.SIDECAR_XML, xml_path.stat().st_size, 1_700_000_000, mp4.path)
            rows = [{"SourceFile": str(mp4.path), "CreateDate": "2026:08:18 20:22:20", "TimeZone": "+09:00"}]
            result = determine_capture_times([mp4, xml], self.exiftool, runner=runner_with(rows))
            wanted = datetime(2026, 8, 18, 9, 10, 11, tzinfo=timezone(-timedelta(hours=4)))
            self.assertEqual(result.capture_times[mp4.path].value, wanted)
            self.assertEqual(result.capture_times[xml.path].value, wanted)
            self.assertEqual(result.capture_times[xml.path].source, "inherited:xml:CreationDate")

    def test_broken_xml_falls_back_to_quicktime_and_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml_path = root / "C0001M01.XML"
            xml_path.write_text("<broken")
            mp4 = self.source(root / "C0001.MP4", SourceKind.VIDEO, xml_path)
            xml = SourceFile(xml_path.absolute(), SourceKind.SIDECAR_XML, xml_path.stat().st_size, 1, mp4.path)
            rows = [{"SourceFile": str(mp4.path), "CreateDate": "2026:08:18 20:22:20", "TimeZone": "+09:00"}]
            result = determine_capture_times([mp4, xml], self.exiftool, runner=runner_with(rows))
            self.assertEqual(result.capture_times[mp4.path].source, "quicktime:CreateDate+TimeZone")
            self.assertEqual(result.capture_times[xml.path].value, result.capture_times[mp4.path].value)
            self.assertEqual(len(result.warnings), 1)

    def test_video_without_xml_uses_quicktime_then_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = self.source(root / "C0001.MP4", SourceKind.VIDEO, mtime=1_700_000_000)
            b = self.source(root / "C0002.MP4", SourceKind.VIDEO, mtime=1_700_000_100)
            rows = [{"SourceFile": str(a.path), "CreateDate": "2026:08:18 20:22:20", "TimeZone": "+09:30"}, {"SourceFile": str(b.path), "CreateDate": "bad", "TimeZone": "+09:00"}]
            result = determine_capture_times([a, b], self.exiftool, runner=runner_with(rows))
            self.assertEqual(result.capture_times[a.path].value.utcoffset(), timedelta(hours=9, minutes=30))
            self.assertEqual(result.capture_times[b.path].source, "mtime")

    def test_exiftool_result_paths_must_exactly_match_requested_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DSC1.JPG"
            source = self.source(path, SourceKind.STILL)
            with self.assertRaises(ValueError):
                read_exiftool_json(self.exiftool, [source], runner=runner_with([{"SourceFile": str(path.parent / "other.JPG")}]))

    def test_untrustworthy_exiftool_output_fails_instead_of_silently_using_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DSC1.JPG"
            source = self.source(path, SourceKind.STILL)
            result = determine_capture_times([source], self.exiftool, runner=runner_with([{"SourceFile": str(path.parent / "other.JPG")}]))
            self.assertFalse(result.capture_times)
            self.assertEqual(result.failures[0].path, source.path)
