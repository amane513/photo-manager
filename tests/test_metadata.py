import subprocess
import unittest
from pathlib import Path

from photo_copy.metadata import MetadataError, capture_timestamp


class CaptureTimestampTest(unittest.TestCase):
    def test_prefers_original_photo_timestamp(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='[{"DateTimeOriginal":"20260911-143052","CreateDate":"20260911-143100"}]',
            )

        self.assertEqual(capture_timestamp(Path("photo.ARW"), run=run), "20260911-143052")

    def test_uses_video_timestamp_when_original_is_missing(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='[{"MediaCreateDate":"20260911-143052"}]',
            )

        self.assertEqual(capture_timestamp(Path("video.MOV"), run=run), "20260911-143052")

    def test_returns_none_when_no_timestamp_exists(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="[{}]")

        self.assertIsNone(capture_timestamp(Path("unknown.bin"), run=run))

    def test_reports_missing_exiftool(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError

        with self.assertRaisesRegex(MetadataError, "ExifToolが見つからない"):
            capture_timestamp(Path("photo.ARW"), run=run)
