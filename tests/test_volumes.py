import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photo_manager.runtime import OperationalError, UsageError
from photo_manager.volumes import discover_source, eject_volume, ensure_capacity, ensure_hard_links, validate_source, validate_volume


def diskutil_result(path, uuid="expected", identifier="disk9s1", parent="disk9"):
    return subprocess.CompletedProcess(
        ["diskutil"], 0,
        plistlib.dumps({"MountPoint": str(path), "VolumeUUID": uuid, "DeviceIdentifier": identifier, "ParentWholeDisk": parent}),
        b"",
    )


class EjectTests(unittest.TestCase):
    """The card is ejected as a whole disk, and only after a fresh recheck."""

    def test_eject_uses_the_parent_whole_disk_not_the_partition(self):
        calls = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def runner(argv, **_kwargs):
                calls.append(list(argv))
                if argv[1] == "info":
                    return diskutil_result(root, identifier="disk8s1", parent="disk8")
                return subprocess.CompletedProcess(argv, 0, b"", b"")

            eject_volume(root, runner=runner, diskutil="/usr/sbin/diskutil")

        self.assertEqual(calls[0][1], "info")
        self.assertEqual(calls[-1], ["/usr/sbin/diskutil", "eject", "disk8"])
        self.assertNotIn("disk8s1", calls[-1])

    def test_mount_point_is_rechecked_immediately_before_eject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            other = root / "moved"
            other.mkdir()
            ejected = []

            def runner(argv, **_kwargs):
                if argv[1] == "info":
                    # diskutil now reports a different mount point for the card.
                    return diskutil_result(other, identifier="disk8s1", parent="disk8")
                ejected.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, b"", b"")

            with self.assertRaises(OperationalError):
                eject_volume(root, runner=runner, diskutil="/usr/sbin/diskutil")
        self.assertEqual(ejected, [])

    def test_failed_eject_is_an_operation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def runner(argv, **_kwargs):
                if argv[1] == "info":
                    return diskutil_result(root, identifier="disk8s1", parent="disk8")
                return subprocess.CompletedProcess(argv, 1, b"", b"could not unmount")

            with self.assertRaises(OperationalError) as caught:
                eject_volume(root, runner=runner, diskutil="/usr/sbin/diskutil")
        self.assertEqual(caught.exception.exit_code, 1)
        self.assertIn("disk8", str(caught.exception))


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

    def test_successful_hard_link_probe_removes_the_tree_it_created(self):
        # The probe runs before the archive lock exists, so a successful
        # preflight must be invisible too, not only a failing one.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_hard_links(root)
            self.assertEqual(list(root.iterdir()), [])

    def test_successful_hard_link_probe_keeps_an_existing_management_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tmp = root / "_photo-manager" / "tmp"
            tmp.mkdir(parents=True)
            ensure_hard_links(root)
            self.assertTrue(tmp.is_dir())
            self.assertEqual(list(tmp.iterdir()), [])

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
