import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import photo_manager.discovery as discovery
from photo_manager.discovery import SourceKind, discover_files


class DiscoveryTests(unittest.TestCase):
    def touch(self, root, relative, contents=b"x"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def test_only_documented_patterns_are_planned_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jpg = self.touch(root, "dCiM/100msdcf/DSC1.jPg")
            arw = self.touch(root, "dCiM/100msdcf/DSC2.aRw")
            mp4 = self.touch(root, "pRiVaTe/m4RoOt/cLiP/C0001.mP4")
            xml = self.touch(root, "pRiVaTe/m4RoOt/cLiP/C0001M01.xMl", b"<x/>")
            self.touch(root, "pRiVaTe/m4RoOt/THMBNL/thumbnail.JPG")
            self.touch(root, "pRiVaTe/m4RoOt/SUB/proxy.MP4")
            self.touch(root, "dCiM/100msdcf/._DSC3.JPG")
            self.touch(root, "pRiVaTe/m4RoOt/cLiP/._C0001M01.XML")
            result = discover_files(root)
            self.assertEqual({item.path for item in result.files}, {jpg, arw, mp4, xml})
            kinds = {item.path: item.kind for item in result.files}
            self.assertEqual(kinds[jpg], SourceKind.STILL)
            self.assertEqual(kinds[mp4], SourceKind.VIDEO)
            self.assertEqual(kinds[xml], SourceKind.SIDECAR_XML)
            self.assertFalse(result.failures)
            self.assertEqual((root / "pRiVaTe/m4RoOt/THMBNL/thumbnail.JPG").read_bytes(), b"x")

    def test_orphan_xml_is_not_planned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            xml = self.touch(root, "PRIVATE/M4ROOT/CLIP/C0001M01.XML")
            result = discover_files(root)
            self.assertEqual(result.files, ())
            self.assertEqual(result.failures[0].path, xml)
            self.assertIn("orphan", result.failures[0].message)

    def test_ambiguous_xml_rejects_the_video_and_candidates(self):
        # exFAT (and this test host's default filesystem) cannot contain two
        # case-only variants.  Feed the lower-level enumerator a duplicated
        # CLIP entry to exercise the fail-safe ambiguity branch nevertheless.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.touch(root, "PRIVATE/M4ROOT/CLIP/C0001.MP4")
            self.touch(root, "PRIVATE/M4ROOT/CLIP/C0001M01.XML")
            private = root / "PRIVATE"
            m4root = private / "M4ROOT"
            clip = m4root / "CLIP"
            def children(parent, wanted):
                return {"DCIM": [], "PRIVATE": [private], "M4ROOT": [m4root], "CLIP": [clip, clip]}[wanted]
            with mock.patch.object(discovery, "_children_named", side_effect=children):
                result = discover_files(root)
            self.assertEqual(result.files, ())
            self.assertGreaterEqual(len(result.failures), 3)
            self.assertIn("multiple", result.failures[0].message)
