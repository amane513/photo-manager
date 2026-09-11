import unittest
from pathlib import Path

from photo_copy.cli import parse_request
from photo_copy.models import Device, TransferKind


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
        self.assertEqual(request.year_month, "2026-09")
        self.assertIs(request.device, Device.CAMERA)
        self.assertIs(request.transfer_kind, TransferKind.LOCAL)
        self.assertTrue(request.dry_run)
