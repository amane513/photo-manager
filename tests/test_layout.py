"""--layout classify/preserveと、モード取り違え・除外の自動テスト。"""

import tempfile
import unittest
from pathlib import Path

from photo_copy.models import CopyRequest, Device, ItemStatus, Layout, TransferKind
from photo_copy.planning import build_plan
from photo_copy.service import execute_copy


class LayoutModeTest(unittest.TestCase):
    def classify_request(self, source: Path, destination: Path, **overrides) -> CopyRequest:
        fields = dict(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            layout=Layout.CLASSIFY,
            year_month="2026-09",
            device=Device.CAMERA,
        )
        fields.update(overrides)
        return CopyRequest(**fields)

    def preserve_request(self, source: Path, destination: Path, **overrides) -> CopyRequest:
        fields = dict(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            layout=Layout.PRESERVE,
        )
        fields.update(overrides)
        return CopyRequest(**fields)

    def test_preserve_mirrors_existing_relative_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            original = source / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.ARW"
            original.parent.mkdir(parents=True)
            original.write_bytes(b"raw")
            destination_root = root / "destination"

            result = execute_copy(self.preserve_request(source, destination_root))

            target = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.ARW"
            self.assertEqual(result.counts()["copied"], 1)
            self.assertEqual(target.read_bytes(), b"raw")
            self.assertTrue(original.exists())

    def test_preserve_does_not_accept_year_month_or_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()

            with self.assertRaises(ValueError):
                build_plan(self.preserve_request(source, root / "destination", year_month="2026-09"))
            with self.assertRaises(ValueError):
                build_plan(self.preserve_request(source, root / "destination", device=Device.CAMERA))

    def test_classify_requires_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()

            with self.assertRaises(ValueError):
                build_plan(
                    CopyRequest(
                        source=source,
                        destination_root=root / "destination",
                        transfer_kind=TransferKind.LOCAL,
                        layout=Layout.CLASSIFY,
                    )
                )

    def test_classify_does_not_require_year_month(self) -> None:
        """--year-monthの省略は、撮影年月への自動分類として受け付ける（第2段階）。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()

            plan = build_plan(
                CopyRequest(
                    source=source,
                    destination_root=root / "destination",
                    transfer_kind=TransferKind.LOCAL,
                    layout=Layout.CLASSIFY,
                    device=Device.CAMERA,
                )
            )

            self.assertEqual(plan, ())

    def test_classify_on_already_placed_tree_is_unresolved(self) -> None:
        """配置済みのツリーをclassifyで処理すると、二重の日時プレフィックスにならず未処理になる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            placed = source / "2026" / "2026-09" / "camera"
            placed.mkdir(parents=True)
            (placed / "20260911-143052_DSC00001.ARW").write_bytes(b"raw")
            destination_root = root / "destination"

            result = execute_copy(
                self.classify_request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260912-000000" for p in paths},
            )

            self.assertEqual(result.counts()["unresolved"], 1)
            self.assertFalse(destination_root.exists())
            self.assertIn("日時プレフィックス", result.items[0].reason or "")

    def test_preserve_on_unorganized_folder_is_unresolved(self) -> None:
        """未整理のフォルダをpreserveで処理すると、想定外の相対配置として未処理になる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "DCIM").mkdir(parents=True)
            (source / "DCIM" / "DSC00001.ARW").write_bytes(b"raw")
            destination_root = root / "destination"

            result = execute_copy(self.preserve_request(source, destination_root))

            self.assertEqual(result.counts()["unresolved"], 1)
            self.assertFalse(destination_root.exists())

    def test_preserve_rejects_mismatched_year_and_bad_month_and_device(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "2026" / "2027-09" / "camera").mkdir(parents=True)
            (source / "2026" / "2027-09" / "camera" / "a.arw").write_bytes(b"x")
            (source / "2026" / "2026-13" / "camera").mkdir(parents=True)
            (source / "2026" / "2026-13" / "camera" / "b.arw").write_bytes(b"x")
            (source / "2026" / "2026-09" / "printer").mkdir(parents=True)
            (source / "2026" / "2026-09" / "printer" / "c.arw").write_bytes(b"x")

            result = execute_copy(self.preserve_request(source, root / "destination"))

            self.assertEqual(result.counts()["unresolved"], 3)

    def test_preserve_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            real_dir = source / "elsewhere"
            real_dir.mkdir(parents=True)
            real_file = real_dir / "a.arw"
            real_file.write_bytes(b"x")
            placed = source / "2026" / "2026-09" / "camera"
            placed.mkdir(parents=True)
            link = placed / "a.arw"
            link.symlink_to(real_file)

            result = execute_copy(self.preserve_request(source, root / "destination"))

            statuses = {item.source.name: item.status for item in result.items if item.source.name == "a.arw"}
            self.assertEqual(statuses["a.arw"], ItemStatus.UNRESOLVED)

    def test_os_junk_files_are_excluded_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / ".DS_Store").write_bytes(b"junk")
            (source / "._resource").write_bytes(b"junk")
            (source / "DSC00001.JPG").write_bytes(b"jpeg")

            result = execute_copy(
                self.classify_request(source, root / "destination"),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
            )

            self.assertEqual(result.counts()["excluded"], 2)
            self.assertEqual(result.counts()["copied"], 1)

    def test_only_restricts_to_relative_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            (source / "DCIM").mkdir(parents=True)
            (source / "PRIVATE").mkdir()
            (source / "DCIM" / "DSC00001.ARW").write_bytes(b"a")
            (source / "PRIVATE" / "DSC00002.ARW").write_bytes(b"b")

            result = execute_copy(
                self.classify_request(source, root / "destination", only=("DCIM",)),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
            )

            self.assertEqual(len(result.items), 1)
            self.assertEqual(result.items[0].source.name, "DSC00001.ARW")

    def test_only_rejects_absolute_or_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()

            with self.assertRaises(ValueError):
                build_plan(self.classify_request(source, root / "destination", only=("/etc",)))
            with self.assertRaises(ValueError):
                build_plan(self.classify_request(source, root / "destination", only=("../escape",)))


class AutoClassifyTest(unittest.TestCase):
    """--year-month省略時の自動分類（第2段階）の自動テスト。"""

    def classify_request(self, source: Path, destination: Path, **overrides) -> CopyRequest:
        fields = dict(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            layout=Layout.CLASSIFY,
            device=Device.CAMERA,
        )
        fields.update(overrides)
        return CopyRequest(**fields)

    def test_files_spanning_multiple_months_are_classified_independently(self) -> None:
        """1回の実行で複数月へ分かれてよい（C09）。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"aug")
            (source / "DSC00002.JPG").write_bytes(b"sep")

            timestamps = {
                source / "DSC00001.JPG": "20260831-235900",
                source / "DSC00002.JPG": "20260901-000100",
            }
            result = execute_copy(
                self.classify_request(source, root / "destination"),
                timestamps_for=lambda paths: {p: timestamps[p] for p in paths},
            )

            self.assertEqual(result.counts()["copied"], 2)
            self.assertTrue((root / "destination" / "2026" / "2026-08" / "camera" / "20260831-235900_DSC00001.JPG").exists())
            self.assertTrue((root / "destination" / "2026" / "2026-09" / "camera" / "20260901-000100_DSC00002.JPG").exists())

    def test_lone_mov_without_arw_or_heic_uses_itself_as_reference(self) -> None:
        """優先順位の拡張により、ARW/HEICを伴わない単独MOVも基準にできる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "CLIP.MOV").write_bytes(b"mov")

            result = execute_copy(
                self.classify_request(source, root / "destination"),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
            )

            self.assertEqual(result.counts()["copied"], 1)

    def test_lone_heic_without_mov_uses_itself_as_reference(self) -> None:
        """Live Photoの組み合わせ（MOV同伴）を前提とせず、単独HEICも基準にできる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "IMG_0001.HEIC").write_bytes(b"heic")

            result = execute_copy(
                self.classify_request(source, root / "destination"),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
            )

            self.assertEqual(result.counts()["copied"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
