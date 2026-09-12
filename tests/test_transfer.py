"""転送層をプロトコルとして分離したことの自動テスト。

service.execute_copy が実際のファイルシステムを直接検査せず、注入した
Transfer 実装の5操作（preflight、facts、digest、ensure_directories、send）
だけを使っていることを確認する。
"""

import tempfile
import unittest
from pathlib import Path

from photo_copy.models import CopyRequest, Device, ItemStatus, TransferKind
from photo_copy.service import execute_copy
from photo_copy.transfer import DestinationFacts, SendOutcome, TransferAborted, TransferFailed


class FakeTransfer:
    """呼び出しを記録するだけの転送層。ローカルのファイルシステムを見ない。

    ``existing`` に含めた配置先は、既定では実際のコピー元と異なるサイズ
    （内容が異なる衝突）として振る舞う。``existing_size`` と ``existing_digest``
    を指定すると、内容一致（スキップ）を模擬できる。
    """

    def __init__(
        self,
        *,
        existing=frozenset(),
        existing_size: int | None = None,
        existing_digest: str | None = None,
        fail_on=frozenset(),
        abort_on=frozenset(),
    ):
        self.existing_paths = frozenset(existing)
        self.existing_size = existing_size if existing_size is not None else 999999
        self.existing_digest = existing_digest
        self.fail_on = frozenset(fail_on)
        self.abort_on = frozenset(abort_on)
        self.preflight_called = False
        self.ensured_directories: list[Path] = []
        self.sent: list[tuple[Path, Path]] = []
        self.digest_called_with: list[Path] = []

    def preflight(self) -> None:
        self.preflight_called = True

    def facts(self, destinations):
        return {
            destination: (
                DestinationFacts(exists=True, is_regular_file=True, size=self.existing_size)
                if destination in self.existing_paths
                else DestinationFacts(exists=False, is_regular_file=False, size=None)
            )
            for destination in destinations
        }

    def digest(self, destinations):
        self.digest_called_with.extend(destinations)
        return {destination: self.existing_digest for destination in destinations}

    def ensure_directories(self, directories) -> None:
        self.ensured_directories.extend(directories)

    def send(self, source: Path, destination: Path) -> SendOutcome:
        self.sent.append((source, destination))
        if destination in self.abort_on:
            raise TransferAborted(f"接続が切断した: {destination}")
        if destination in self.fail_on:
            raise TransferFailed(f"転送に失敗した: {destination}")
        return SendOutcome.COPIED


class TransferProtocolTest(unittest.TestCase):
    def request(self, source: Path, destination: Path) -> CopyRequest:
        return CopyRequest(
            source=source,
            destination_root=destination,
            transfer_kind=TransferKind.LOCAL,
            year_month="2026-09",
            device=Device.CAMERA,
            dry_run=False,
        )

    def test_conflict_is_decided_by_transfer_not_local_filesystem(self) -> None:
        """destination.exists() がFalseでも、転送層が既存（サイズ不一致）と答えれば衝突にする。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            destination_root = root / "destination"
            target = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            transfer = FakeTransfer(existing={target})
            result = execute_copy(
                self.request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
                transfer=transfer,
            )

            self.assertTrue(transfer.preflight_called)
            self.assertEqual(result.items[0].status, ItemStatus.CONFLICT)
            self.assertEqual(transfer.sent, [])
            self.assertFalse(destination_root.exists())
            # サイズが異なる時点で衝突が確定するため、ハッシュを計算しない。
            self.assertEqual(transfer.digest_called_with, [])

    def test_matching_size_and_hash_is_skipped_not_sent(self) -> None:
        """サイズとSHA-256が一致する既存の配置先はスキップし、転送しない。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            destination_root = root / "destination"
            target = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            transfer = FakeTransfer(existing={target}, existing_size=len(b"jpeg"), existing_digest="same-hash")
            result = execute_copy(
                self.request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
                transfer=transfer,
                source_digest_for=lambda _path: "same-hash",
            )

            self.assertEqual(result.items[0].status, ItemStatus.SKIPPED)
            self.assertEqual(transfer.sent, [])

    def test_matching_size_but_different_hash_is_conflict(self) -> None:
        """サイズが一致してもSHA-256が異なれば内容が異なるとして衝突にする。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            destination_root = root / "destination"
            target = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            transfer = FakeTransfer(existing={target}, existing_size=len(b"jpeg"), existing_digest="different-hash")
            result = execute_copy(
                self.request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
                transfer=transfer,
                source_digest_for=lambda _path: "same-hash",
            )

            self.assertEqual(result.items[0].status, ItemStatus.CONFLICT)
            self.assertIn("内容が異なる", result.items[0].reason or "")
            self.assertEqual(transfer.sent, [])

    def test_transfer_failed_marks_item_failed_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            (source / "DSC00002.JPG").write_bytes(b"jpeg")
            destination_root = root / "destination"
            failing = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            transfer = FakeTransfer(fail_on={failing})
            result = execute_copy(
                self.request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
                transfer=transfer,
            )

            statuses = {item.source.name: item.status for item in result.items}
            self.assertEqual(statuses["DSC00001.JPG"], ItemStatus.FAILED)
            self.assertEqual(statuses["DSC00002.JPG"], ItemStatus.COPIED)
            self.assertFalse(result.aborted)

    def test_transfer_aborted_marks_remaining_items_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "DSC00001.JPG").write_bytes(b"jpeg")
            (source / "DSC00002.JPG").write_bytes(b"jpeg")
            destination_root = root / "destination"
            aborting = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            transfer = FakeTransfer(abort_on={aborting})
            result = execute_copy(
                self.request(source, destination_root),
                timestamps_for=lambda paths: {p: "20260911-143052" for p in paths},
                transfer=transfer,
            )

            statuses = {item.source.name: item.status for item in result.items}
            self.assertEqual(statuses["DSC00001.JPG"], ItemStatus.FAILED)
            self.assertEqual(statuses["DSC00002.JPG"], ItemStatus.UNRESOLVED)
            self.assertTrue(result.aborted)
            self.assertIn("接続が切断した", result.abort_reason or "")
            # 中断後のファイルには転送層のsend()を呼ばない。
            self.assertEqual(len(transfer.sent), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
