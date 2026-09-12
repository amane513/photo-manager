import json
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

    def test_timezone_defaults_to_fixed_value_when_omitted(self) -> None:
        """decisions.md 2026-09-12: 動画のTZは実行ホスト任せではなく固定値を既定とする。"""

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
                exit_code = main(args)

            self.assertEqual(exit_code, 0)
            log = next(logs.glob("*.json"))
            payload = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(payload["timezone"], "Asia/Tokyo")

    def test_explicit_timezone_overrides_default(self) -> None:
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
                "--timezone",
                "UTC",
            ]

            with patch("photo_copy.cli.capture_timestamps", lambda paths, tz=None: {p: "20260911-143052" for p in paths}):
                exit_code = main(args)

            self.assertEqual(exit_code, 0)
            log = next(logs.glob("*.json"))
            payload = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(payload["timezone"], "UTC")


class ProfileTest(unittest.TestCase):
    """段階5: プロファイル設定（--profile、--profile-config）の自動テスト。"""

    def fake_timestamps(self, paths, tz=None):
        return {p: "20260911-143052" for p in paths}

    def test_profile_supplies_omitted_arguments(self) -> None:
        """C21相当: --profileで指定した値が、明示していない引数の既定値になる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg-1")
            destination = root / "destination"
            logs = root / "logs"
            profile_config = root / "profiles.ini"
            profile_config.write_text(
                "[profile.sd-to-mac]\n"
                f"source = {source}\n"
                f"destination-root = {destination}\n"
                "device = camera\n"
                f"log-dir = {logs}\n",
                encoding="utf-8",
            )

            with patch("photo_copy.cli.capture_timestamps", self.fake_timestamps):
                exit_code = main(
                    [
                        "copy",
                        "--profile",
                        "sd-to-mac",
                        "--profile-config",
                        str(profile_config),
                        "--year-month",
                        "2026-09",
                    ]
                )

            self.assertEqual(exit_code, 0)
            target = destination / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"
            self.assertTrue(target.exists())
            log = next(logs.glob("*.json"))
            payload = json.loads(log.read_text(encoding="utf-8"))
            self.assertEqual(payload["profile"], "sd-to-mac")
            self.assertEqual(payload["source"], str(source))
            self.assertEqual(payload["destination_root"], str(destination))
            self.assertEqual(payload["device"], "camera")

    def test_command_line_argument_overrides_profile_value(self) -> None:
        """優先順位「コマンドライン引数 > プロファイル > CLIの既定値」を確認する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg-1")
            profile_destination = root / "from-profile"
            override_destination = root / "from-cli"
            logs = root / "logs"
            profile_config = root / "profiles.ini"
            profile_config.write_text(
                "[profile.sd-to-mac]\n"
                f"source = {source}\n"
                f"destination-root = {profile_destination}\n"
                "device = camera\n"
                f"log-dir = {logs}\n",
                encoding="utf-8",
            )

            with patch("photo_copy.cli.capture_timestamps", self.fake_timestamps):
                exit_code = main(
                    [
                        "copy",
                        "--profile",
                        "sd-to-mac",
                        "--profile-config",
                        str(profile_config),
                        "--destination-root",
                        str(override_destination),
                        "--year-month",
                        "2026-09",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(profile_destination.exists())
            target = override_destination / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"
            self.assertTrue(target.exists())

    def test_unknown_profile_name_is_unrunnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_config = root / "profiles.ini"
            profile_config.write_text("[profile.other]\nsource = /tmp\n", encoding="utf-8")

            exit_code = main(
                [
                    "copy",
                    "--profile",
                    "does-not-exist",
                    "--profile-config",
                    str(profile_config),
                    "--destination-root",
                    str(root / "destination"),
                    "--year-month",
                    "2026-09",
                    "--device",
                    "camera",
                ]
            )

            self.assertEqual(exit_code, 2)

    def test_profile_is_not_read_without_explicit_profile_flag(self) -> None:
        """--profile-configだけを指定しても、--profileを指定しない限りプロファイルは読まない。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            profile_config = root / "profiles.ini"
            profile_config.write_text("[profile.unused]\nsource = /should/not/be/used\n", encoding="utf-8")

            exit_code = main(
                [
                    "copy",
                    "--profile-config",
                    str(profile_config),
                    "--destination-root",
                    str(root / "destination"),
                    "--year-month",
                    "2026-09",
                    "--device",
                    "camera",
                ]
            )

            # --sourceが無く、プロファイルも読まれないため実行不能になる。
            self.assertEqual(exit_code, 2)

    def test_missing_source_without_profile_is_unrunnable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            exit_code = main(
                [
                    "copy",
                    "--destination-root",
                    str(root / "destination"),
                    "--year-month",
                    "2026-09",
                    "--device",
                    "camera",
                ]
            )

            self.assertEqual(exit_code, 2)
