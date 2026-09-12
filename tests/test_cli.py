import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_rerun_of_fully_copied_source_exits_zero(self) -> None:
        """C20: CLI経由でも、送信済みの範囲の再実行は全件スキップで正常終了する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg-1")
            logs = root / "logs"
            args = [
                "copy",
                "--source",
                str(source),
                "--destination-root",
                str(root / "destination"),
                "--year-month",
                "2026-09",
                "--device",
                "camera",
                "--log-dir",
                str(logs),
            ]

            with patch("photo_copy.cli.capture_timestamps", lambda paths, tz=None: {p: "20260911-143052" for p in paths}):
                first_exit = main(args)
                second_exit = main(args)

            self.assertEqual(first_exit, 0)
            self.assertEqual(second_exit, 0)
