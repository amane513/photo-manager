"""scripts/hosts/*.env の厳密なKEY=VALUE解析の自動テスト。"""

import tempfile
import unittest
from pathlib import Path

from photo_copy.hosts import load_host_config

VALID_CONTENT = """\
# コメント行
PRIMARY_STORAGE_UUID=0574e6d5-893c-41b5-84e8-77c41c3b59c1
PRIMARY_STORAGE_FSTYPE=ext4
ARCHIVE_MOUNT=/mnt/camera_archive
ARCHIVE_OWNER=amane-yajima
ARCHIVE_GROUP=amane-yajima
SMB_SHARE_NAME=CameraArchive
SMB_VALID_USER=amane-yajima
SSH_HOST=ubuntu
"""


class LoadHostConfigTest(unittest.TestCase):
    def test_valid_file_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ubuntu.env"
            path.write_text(VALID_CONTENT, encoding="utf-8")

            config = load_host_config(path)

            self.assertEqual(config.primary_storage_uuid, "0574e6d5-893c-41b5-84e8-77c41c3b59c1")
            self.assertEqual(config.archive_mount, Path("/mnt/camera_archive"))
            self.assertEqual(config.archive_owner, "amane-yajima")
            self.assertEqual(config.ssh_host, "ubuntu")

    def test_missing_required_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ubuntu.env"
            path.write_text(VALID_CONTENT.replace("SSH_HOST=ubuntu\n", ""), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_host_config(path)

    def test_empty_required_value_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ubuntu.env"
            path.write_text(VALID_CONTENT.replace("SSH_HOST=ubuntu\n", "SSH_HOST=\n"), encoding="utf-8")

            with self.assertRaises(ValueError):
                load_host_config(path)

    def test_malformed_line_is_rejected_without_executing_it(self) -> None:
        """シェルを介さないため、KEY=VALUE以外の行は実行されず拒否される。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ubuntu.env"
            path.write_text(VALID_CONTENT + "$(rm -rf /)\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_host_config(path)

    def test_missing_file_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_host_config(Path("/nonexistent/ubuntu.env"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
