import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from photo_copy.cli import main
from photo_copy.models import CopyRequest, Device, ItemStatus, TransferKind
from photo_copy.planning import build_plan
from photo_copy.service import execute_copy, result_as_dict


class CopyServiceTest(unittest.TestCase):
    def request(self, source: Path, destination: Path, *, dry_run: bool = False) -> CopyRequest:
        return CopyRequest(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            year_month="2026-09",
            device=Device.CAMERA,
            dry_run=dry_run,
        )

    def test_copies_with_timestamp_prefix_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            original = source / "DCIM" / "DSC00001.ARW"
            original.parent.mkdir()
            original.write_bytes(b"raw")
            destination = root / "destination"

            result = execute_copy(self.request(source, destination), timestamps_for=lambda paths: {p: "20260911-143052" for p in paths})

            target = destination / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.ARW"
            self.assertEqual(result.counts()["copied"], 1)
            self.assertEqual(target.read_bytes(), b"raw")
            self.assertTrue(original.exists())

    def test_dry_run_does_not_change_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            destination = root / "destination"

            result = execute_copy(self.request(source, destination, dry_run=True), timestamps_for=lambda paths: {p: "20260911-143052" for p in paths})

            self.assertEqual(result.counts()["planned"], 1)
            self.assertFalse(destination.exists())

    def test_existing_file_is_reported_as_conflict_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"new")
            destination = root / "destination" / "2026" / "2026-09" / "camera"
            destination.mkdir(parents=True)
            target = destination / "20260911-143052_DSC00001.JPG"
            target.write_bytes(b"existing")

            result = execute_copy(self.request(source, root / "destination"), timestamps_for=lambda paths: {p: "20260911-143052" for p in paths})

            self.assertEqual(result.items[0].status, ItemStatus.CONFLICT)
            self.assertEqual(target.read_bytes(), b"existing")

    def test_two_inputs_with_same_destination_are_both_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "DCIM").mkdir(parents=True)
            (source / "PRIVATE").mkdir()
            (source / "DCIM" / "CLIP.MOV").write_bytes(b"one")
            (source / "PRIVATE" / "CLIP.MOV").write_bytes(b"two")

            result = execute_copy(self.request(source, root / "destination"), timestamps_for=lambda paths: {p: "20260911-143052" for p in paths})

            self.assertEqual(result.counts()["conflict"], 2)
            self.assertFalse((root / "destination").exists())

    def test_arw_group_uses_reference_timestamp_for_jpeg_and_xmp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            arw = source / "DSC00001.ARW"
            jpeg = source / "DSC00001.JPG"
            xmp = source / "DSC00001.ARW.xmp"
            for path in (arw, jpeg, xmp):
                path.write_bytes(b"data")

            requested_paths: list[Path] = []

            def timestamps_for(paths):
                requested_paths.extend(paths)
                return {path: "20260911-143052" for path in paths}

            plan = build_plan(
                self.request(source, Path(directory) / "destination"),
                timestamps_for=timestamps_for,
            )

            self.assertEqual({item.timestamp for item in plan}, {"20260911-143052"})
            self.assertTrue(all(item.status is ItemStatus.PLANNED for item in plan))
            self.assertEqual(requested_paths, [arw])

    def test_group_without_reference_is_unresolved_and_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            (source / "DSC00001.ARW.xmp").write_bytes(b"xmp")

            result = execute_copy(self.request(source, root / "destination"), timestamps_for=lambda paths: {p: "20260911-143052" for p in paths})

            self.assertEqual(result.counts()["unresolved"], 2)
            self.assertFalse((root / "destination").exists())
            self.assertIn("基準ファイルがない", result.items[0].reason or "")

    def test_out_of_range_timestamp_is_unresolved_not_misplaced(self) -> None:
        """カメラの時計リセット相当の日時は、推測で配置せず未処理として報告する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")

            plan = build_plan(
                self.request(source, root / "destination"),
                timestamps_for=lambda paths: {p: "19700101-000000" for p in paths},
                now=datetime(2026, 9, 12),
            )

            self.assertEqual(plan[0].status, ItemStatus.UNRESOLVED)
            self.assertIn("19700101-000000", plan[0].reason or "")

    def test_unknown_format_is_reported_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "notes.txt").write_text("keep")

            result = execute_copy(self.request(source, root / "destination"), timestamps_for=lambda paths: {p: None for p in paths})

            self.assertEqual(result.items[0].status, ItemStatus.UNRESOLVED)
            self.assertEqual(result_as_dict(result)["counts"]["unresolved"], 1)

    def test_cli_writes_structured_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "unsupported.txt").write_text("x")
            logs = root / "logs"

            exit_code = main([
                "copy", "--source", str(source), "--destination-root", str(root / "destination"),
                "--year-month", "2026-09", "--device", "camera", "--log-dir", str(logs),
            ])

            self.assertEqual(exit_code, 1)
            log = next(logs.glob("*.json"))
            self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["counts"]["unresolved"], 1)
