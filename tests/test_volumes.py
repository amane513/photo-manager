import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photo_manager.runtime import UsageError
from photo_manager.volumes import discover_source, ensure_capacity, ensure_hard_links, validate_source, validate_volume


def diskutil_result(path, uuid="expected"):
    return subprocess.CompletedProcess(
        ["diskutil"], 0,
        plistlib.dumps({"MountPoint": str(path), "VolumeUUID": uuid, "DeviceIdentifier": "disk9s1", "ParentWholeDisk": "disk9"}),
        b"",
    )


class VolumeTests(unittest.TestCase):
    def test_uuid_is_checked_from_diskutil_plist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = validate_volume(root, "EXPECTED", runner=lambda *a, **k: diskutil_result(root))
        self.assertEqual(info.parent_whole_disk, "disk9")

    def test_uuid_mismatch_is_usage_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(UsageError):
                validate_volume(root, "other", runner=lambda *a, **k: diskutil_result(root))

    def test_hard_link_failure_leaves_no_probe_or_new_management_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("photo_manager.volumes.os.link", side_effect=OSError("unsupported")):
                with self.assertRaises(UsageError):
                    ensure_hard_links(root)
            self.assertFalse((root / "_photo-manager").exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_hard_link_probe_leaves_no_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_hard_links(root)
            self.assertEqual(list((root / "_photo-manager" / "tmp").iterdir()), [])

    def test_source_auto_detection_is_unambiguous_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            volumes = Path(directory)
            dest = volumes / "archive"
            card = volumes / "card"
            dest.mkdir()
            (card / "DCIM").mkdir(parents=True)
            self.assertEqual(discover_source(dest, volumes_root=volumes), card)
            self.assertEqual(list(card.iterdir()), [card / "DCIM"])
            (volumes / "other" / "PRIVATE" / "M4ROOT").mkdir(parents=True)
            with self.assertRaises(UsageError):
                discover_source(dest, volumes_root=volumes)

    def test_explicit_source_cannot_be_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "DCIM").mkdir()
            with self.assertRaises(UsageError):
                validate_source(root, destination=root)

    def test_capacity_rejects_insufficient_space(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("photo_manager.volumes.shutil.disk_usage", return_value=mock.Mock(free=9)):
                with self.assertRaises(UsageError):
                    ensure_capacity(Path(directory), 10, 1.1)
