"""第2段階 段階4: 部分失敗・中断・一時ファイル残存後の再実行の自動テスト。

再実行は同じコマンドをもう一度実行する形であり、`--resume` のような専用の
仕組みは持たない。内容一致によるスキップ（段階3）だけで、前回どこまで進んだかを
記録せずに安全な再実行が成立することを確認する。
"""

import tempfile
import unittest
from pathlib import Path

from photo_copy.local import LocalTransfer
from photo_copy.models import CopyRequest, Device, ItemStatus, TransferKind
from photo_copy.service import execute_copy
from photo_copy.transfer import TransferAborted, TransferFailed


def _is_success_exit(result) -> bool:
    """cli.pyの終了コード判定と同じ式。conflict・failed・unresolvedが無ければ正常終了とする。"""

    counts = result.counts()
    return not (counts["conflict"] or counts["failed"] or counts["unresolved"])


class _DelegatingLocalTransfer:
    """LocalTransferへ委譲するだけの土台。send()だけをテストごとに差し替える。"""

    def __init__(self) -> None:
        self._inner = LocalTransfer()

    def preflight(self) -> None:
        self._inner.preflight()

    def facts(self, destinations):
        return self._inner.facts(destinations)

    def digest(self, destinations):
        return self._inner.digest(destinations)

    def ensure_directories(self, directories) -> None:
        self._inner.ensure_directories(directories)

    def send(self, source: Path, destination: Path):
        return self._inner.send(source, destination)


class FlakyOnceTransfer(_DelegatingLocalTransfer):
    """指定したコピー元だけ、最初の1回はTransferFailedになるLocalTransfer。"""

    def __init__(self, fail_once_for) -> None:
        super().__init__()
        self._fail_once_for = set(fail_once_for)
        self._already_failed: set[Path] = set()

    def send(self, source: Path, destination: Path):
        if source in self._fail_once_for and source not in self._already_failed:
            self._already_failed.add(source)
            raise TransferFailed("一時的な失敗を模擬する")
        return super().send(source, destination)


class AbortOnceTransfer(_DelegatingLocalTransfer):
    """指定したコピー元の送信時に、最初の1回だけTransferAbortedになるLocalTransfer。"""

    def __init__(self, abort_once_for) -> None:
        super().__init__()
        self._abort_once_for = set(abort_once_for)
        self._already_aborted: set[Path] = set()

    def send(self, source: Path, destination: Path):
        if source in self._abort_once_for and source not in self._already_aborted:
            self._already_aborted.add(source)
            raise TransferAborted("接続が切断したことを模擬する")
        return super().send(source, destination)


class RerunTest(unittest.TestCase):
    def request(self, source: Path, destination: Path, **overrides) -> CopyRequest:
        fields = dict(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            year_month="2026-09",
            device=Device.CAMERA,
        )
        fields.update(overrides)
        return CopyRequest(**fields)

    def test_rerun_after_full_success_skips_everything_and_exits_normally(self) -> None:
        """C20: 送信済みの範囲を再実行すると全件がスキップになり、正常終了する。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg-1")
            (source / "DSC00002.JPG").write_bytes(b"jpeg-2")
            destination = root / "destination"
            timestamps_for = lambda paths: {p: "20260911-143052" for p in paths}  # noqa: E731

            first = execute_copy(self.request(source, destination), timestamps_for=timestamps_for)
            second = execute_copy(self.request(source, destination), timestamps_for=timestamps_for)

            self.assertEqual(first.counts()["copied"], 2)
            self.assertTrue(_is_success_exit(first))

            self.assertEqual(second.counts()["skipped"], 2)
            self.assertEqual(second.counts()["copied"], 0)
            self.assertTrue(_is_success_exit(second))

    def test_rerun_after_partial_failure_completes_remaining_without_resending_success(self) -> None:
        """部分失敗の後、成功済みの1件を再送せず、失敗した1件だけを完了できる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            ok = source / "DSC00001.JPG"
            ok.write_bytes(b"jpeg-1")
            flaky = source / "DSC00002.JPG"
            flaky.write_bytes(b"jpeg-2")
            destination = root / "destination"
            timestamps_for = lambda paths: {p: "20260911-143052" for p in paths}  # noqa: E731

            transfer = FlakyOnceTransfer(fail_once_for={flaky})
            first = execute_copy(self.request(source, destination), timestamps_for=timestamps_for, transfer=transfer)
            self.assertEqual(first.counts()["copied"], 1)
            self.assertEqual(first.counts()["failed"], 1)
            self.assertFalse(_is_success_exit(first))

            second = execute_copy(self.request(source, destination), timestamps_for=timestamps_for, transfer=transfer)

            self.assertEqual(second.counts()["skipped"], 1, "前回成功した1件は再送しない")
            self.assertEqual(second.counts()["copied"], 1, "前回失敗した1件は今回成功する")
            self.assertEqual(second.counts()["failed"], 0)
            self.assertTrue(_is_success_exit(second))

    def test_rerun_after_abort_completes_remaining_items(self) -> None:
        """中断（TransferAborted）により未処理になった残りも、再実行で完了できる。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            first_file = source / "DSC00001.JPG"
            first_file.write_bytes(b"jpeg-1")
            second_file = source / "DSC00002.JPG"
            second_file.write_bytes(b"jpeg-2")
            destination = root / "destination"
            timestamps_for = lambda paths: {p: "20260911-143052" for p in paths}  # noqa: E731

            transfer = AbortOnceTransfer(abort_once_for={first_file})
            first = execute_copy(self.request(source, destination), timestamps_for=timestamps_for, transfer=transfer)

            self.assertTrue(first.aborted)
            statuses = {item.source.name: item.status for item in first.items}
            self.assertEqual(statuses["DSC00001.JPG"], ItemStatus.FAILED)
            self.assertEqual(statuses["DSC00002.JPG"], ItemStatus.UNRESOLVED)
            # ディレクトリ自体はensure_directories()で先に作られるが、中身は書き込まれていない。
            camera_dir = destination / "2026" / "2026-09" / "camera"
            self.assertEqual(list(camera_dir.iterdir()) if camera_dir.exists() else [], [])

            second = execute_copy(self.request(source, destination), timestamps_for=timestamps_for, transfer=LocalTransfer())

            self.assertEqual(second.counts()["copied"], 2)
            self.assertEqual(second.counts()["failed"], 0)
            self.assertEqual(second.counts()["unresolved"], 0)
            self.assertTrue(_is_success_exit(second))

    def test_leftover_temp_file_from_local_transfer_does_not_block_rerun(self) -> None:
        """中断で残った一時ファイルは掃除されないが、計画にも衝突判定にも影響しない。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg-1")
            destination_dir = root / "destination" / "2026" / "2026-09" / "camera"
            destination_dir.mkdir(parents=True)
            leftover = destination_dir / ".20260911-143052_DSC00001.JPG.photo-copy-deadbeef.part"
            leftover.write_bytes(b"incomplete")

            result = execute_copy(
                self.request(source, root / "destination"),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
            )

            target = destination_dir / "20260911-143052_DSC00001.JPG"
            self.assertEqual(result.counts()["copied"], 1)
            self.assertEqual(target.read_bytes(), b"jpeg-1")
            self.assertTrue(leftover.exists(), "一時ファイルの自動削除は対象外である")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
