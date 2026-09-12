import subprocess
import unittest
from datetime import datetime
from pathlib import Path

from photo_copy.metadata import (
    MetadataError,
    capture_timestamp,
    capture_timestamps,
    is_timestamp_in_valid_range,
    resolve_timezone,
)


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


class CaptureTimestampsTest(unittest.TestCase):
    def test_reads_all_paths_from_stdin_in_one_call(self) -> None:
        calls: list[dict] = []

        def run(command, **kwargs):
            calls.append({"command": command, **kwargs})
            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    '[{"DateTimeOriginal":"20260911-143052"},'
                    '{"MediaCreateDate":"20260911-150000"}]'
                ).encode(),
            )

        result = capture_timestamps([Path("a.arw"), Path("b.mov")], run=run)

        self.assertEqual(
            result,
            {Path("a.arw"): "20260911-143052", Path("b.mov"): "20260911-150000"},
        )
        # 一括呼び出しであるため、subprocess.run自体は1回だけ呼ばれる。
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["command"], ["exiftool", "-@", "-"])
        argfile = calls[0]["input"].decode()
        self.assertIn("a.arw", argfile)
        self.assertIn("b.mov", argfile)

    def test_empty_paths_does_not_call_exiftool(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            raise AssertionError("呼ばれないはず")

        self.assertEqual(capture_timestamps([], run=run), {})

    def test_record_count_mismatch_is_fatal(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=b'[{"DateTimeOriginal":"20260911-143052"}]')

        with self.assertRaises(MetadataError):
            capture_timestamps([Path("a.arw"), Path("b.arw")], run=run)

    def test_invalid_json_is_fatal(self) -> None:
        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"not json")

        with self.assertRaises(MetadataError):
            capture_timestamps([Path("a.arw")], run=run)

    def test_nonzero_exit_with_valid_json_is_not_fatal(self) -> None:
        """一部ファイルの処理失敗によるexiftoolの非ゼロ終了は、全体失敗として扱わない。"""

        def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=b'[{"DateTimeOriginal":"20260911-143052"},{"Error":"File not found"}]',
            )

        result = capture_timestamps([Path("a.arw"), Path("broken.arw")], run=run)

        self.assertEqual(result[Path("a.arw")], "20260911-143052")
        self.assertIsNone(result[Path("broken.arw")])

    def test_tz_is_passed_as_environment_variable(self) -> None:
        captured_env: dict = {}

        def run(*_args: object, env=None, **_kwargs: object) -> subprocess.CompletedProcess:
            captured_env.update(env or {})
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=b"[{}]")

        capture_timestamps([Path("a.mov")], tz="Asia/Tokyo", run=run)

        self.assertEqual(captured_env.get("TZ"), "Asia/Tokyo")


class ResolveTimezoneTest(unittest.TestCase):
    def test_explicit_value_is_used_as_is(self) -> None:
        self.assertEqual(resolve_timezone("Asia/Tokyo"), "Asia/Tokyo")

    def test_omitted_value_resolves_to_a_non_empty_string(self) -> None:
        self.assertTrue(resolve_timezone(None))


class IsTimestampInValidRangeTest(unittest.TestCase):
    def test_before_1990_is_invalid(self) -> None:
        now = datetime(2026, 9, 12)
        self.assertFalse(is_timestamp_in_valid_range("19891231-235959", now=now))

    def test_boundary_1990_is_valid(self) -> None:
        now = datetime(2026, 9, 12)
        self.assertTrue(is_timestamp_in_valid_range("19900101-000000", now=now))

    def test_far_future_is_invalid(self) -> None:
        now = datetime(2026, 9, 12)
        self.assertFalse(is_timestamp_in_valid_range("20260914-000000", now=now))

    def test_next_day_is_valid(self) -> None:
        now = datetime(2026, 9, 12, 10, 0, 0)
        self.assertTrue(is_timestamp_in_valid_range("20260913-090000", now=now))

    def test_malformed_value_is_invalid(self) -> None:
        self.assertFalse(is_timestamp_in_valid_range("not-a-timestamp"))
