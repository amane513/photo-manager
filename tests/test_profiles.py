"""~/.config/photo-copy/profiles.ini の読み込みと検証の自動テスト。"""

import tempfile
import unittest
from pathlib import Path

from photo_copy.profiles import load_profile

VALID_CONTENT = """\
[profile.sd-to-ubuntu]
source = /Volumes/Untitled/DCIM
destination-root = /mnt/camera_archive
transport = rsync-ssh
host-config = scripts/hosts/ubuntu.env
layout = date
device = sony-a7c2
log-dir = /var/log/photo-copy
timezone = Asia/Tokyo
only =
    DCIM/100MSDCF
    PRIVATE
"""


class LoadProfileTest(unittest.TestCase):
    def test_valid_profile_with_scalar_keys_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            path.write_text(VALID_CONTENT, encoding="utf-8")

            profile = load_profile(path, "sd-to-ubuntu")

            self.assertEqual(profile.name, "sd-to-ubuntu")
            self.assertEqual(profile.source, "/Volumes/Untitled/DCIM")
            self.assertEqual(profile.destination_root, "/mnt/camera_archive")
            self.assertEqual(profile.transport, "rsync-ssh")
            self.assertEqual(profile.host_config, "scripts/hosts/ubuntu.env")
            self.assertEqual(profile.layout, "date")
            self.assertEqual(profile.device, "sony-a7c2")
            self.assertEqual(profile.log_dir, "/var/log/photo-copy")
            self.assertEqual(profile.timezone, "Asia/Tokyo")

    def test_multiline_only_value_becomes_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            path.write_text(VALID_CONTENT, encoding="utf-8")

            profile = load_profile(path, "sd-to-ubuntu")

            self.assertEqual(profile.only, ("DCIM/100MSDCF", "PRIVATE"))

    def test_missing_only_key_results_in_empty_tuple(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            content = "[profile.no-only]\nsource = /Volumes/Untitled/DCIM\n"
            path.write_text(content, encoding="utf-8")

            profile = load_profile(path, "no-only")

            self.assertEqual(profile.only, ())

    def test_unknown_profile_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            path.write_text(VALID_CONTENT, encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(path, "does-not-exist")

    def test_unrecognized_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            content = "[profile.typo]\nsoruce = /Volumes/Untitled/DCIM\n"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(path, "typo")

    def test_year_month_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            content = "[profile.bad]\nyear-month = 2024-01\n"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(path, "bad")

    def test_dry_run_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            content = "[profile.bad]\ndry-run = true\n"
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(ValueError):
                load_profile(path, "bad")

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_profile(Path("/nonexistent/profiles.ini"), "sd-to-ubuntu")

    def test_other_malformed_profile_does_not_block_loading_well_formed_one(self) -> None:
        content = VALID_CONTENT + "\n[profile.broken]\nsoruce = typo\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.ini"
            path.write_text(content, encoding="utf-8")

            profile = load_profile(path, "sd-to-ubuntu")

            self.assertEqual(profile.source, "/Volumes/Untitled/DCIM")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
