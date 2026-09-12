import tempfile
import unittest
from pathlib import Path

from photo_copy.cli import main, parse_request
from photo_copy.models import Device, Layout, TransferKind


class CopyRequestTest(unittest.TestCase):
    def test_copy_request_is_parsed(self) -> None:
        request = parse_request(
            [
                "copy",
                "--source",
                "/Volumes/SONY/DCIM",
                "--destination-root",
                "/tmp/photo-work",
                "--year-month",
                "2026-09",
                "--device",
                "camera",
                "--transport",
                "local",
                "--dry-run",
            ]
        )

        self.assertEqual(request.source, Path("/Volumes/SONY/DCIM"))
        self.assertEqual(request.destination_root, Path("/tmp/photo-work"))
        self.assertIs(request.layout, Layout.CLASSIFY)
        self.assertEqual(request.year_month, "2026-09")
        self.assertIs(request.device, Device.CAMERA)
        self.assertIs(request.transfer_kind, TransferKind.LOCAL)
        self.assertTrue(request.dry_run)

    def test_preserve_layout_does_not_require_year_month_or_device(self) -> None:
        request = parse_request(
            [
                "copy",
                "--source",
                "/Users/amane/Pictures/PhotoWork",
                "--destination-root",
                "/tmp/photo-work",
                "--layout",
                "preserve",
            ]
        )

        self.assertIs(request.layout, Layout.PRESERVE)
        self.assertIsNone(request.year_month)
        self.assertIsNone(request.device)

    def test_only_can_be_repeated(self) -> None:
        request = parse_request(
            [
                "copy",
                "--source",
                "/Volumes/SONY",
                "--destination-root",
                "/tmp/photo-work",
                "--year-month",
                "2026-09",
                "--device",
                "camera",
                "--only",
                "DCIM/100MSDCF",
                "--only",
                "PRIVATE",
            ]
        )

        self.assertEqual(request.only, ("DCIM/100MSDCF", "PRIVATE"))

    def test_rsync_ssh_without_host_config_is_unrunnable(self) -> None:
        """実機のSSH接続先へは触れず、必須引数の不足だけで実行不能（終了コード2）になることを確認する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()

            exit_code = main(
                [
                    "copy",
                    "--source",
                    str(root / "source"),
                    "--year-month",
                    "2026-09",
                    "--device",
                    "camera",
                    "--transport",
                    "rsync-ssh",
                    "--log-dir",
                    str(root / "logs"),
                ]
            )

            self.assertEqual(exit_code, 2)

    def test_check_without_valid_host_config_is_unrunnable(self) -> None:
        exit_code = main(["check", "--host-config", "/nonexistent/ubuntu.env"])

        self.assertEqual(exit_code, 2)
