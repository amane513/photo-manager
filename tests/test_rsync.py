"""rsync over SSH転送層の自動テスト。

実機のSSH接続先へは接続せず、subprocess.runの代わりにコマンド内容を見て
応答を返すフェイクを注入する。
"""

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from photo_copy.hosts import HostConfig
from photo_copy.models import CopyRequest, Device, TransferKind
from photo_copy.rsync import _ENSURE_DIRECTORIES_SCRIPT, _PREFLIGHT_FACTS_SCRIPT, RsyncSshTransfer
from photo_copy.service import execute_copy
from photo_copy.transfer import DestinationFacts, SendOutcome, TransferAborted, TransferFailed, TransferUnavailable


def make_host_config(**overrides) -> HostConfig:
    fields = dict(
        primary_storage_uuid="0574e6d5-uuid",
        primary_storage_fstype="ext4",
        archive_mount=Path("/mnt/camera_archive"),
        archive_library_root=Path("/mnt/camera_archive/photo-library"),
        archive_owner="amane-yajima",
        archive_group="amane-yajima",
        smb_share_name="CameraArchive",
        smb_valid_user="amane-yajima",
        ssh_host="ubuntu",
    )
    fields.update(overrides)
    return HostConfig(**fields)


def completed(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


VALID_FACTS = (
    b"OWNER=amane-yajima\n"
    b"MOUNTED=1\n"
    b"UUID=0574e6d5-uuid\n"
    b"DESTINATION_UNDER_LIBRARY_ROOT=1\n"
    b"DESTINATION_WRITABLE=1\n"
    b"RSYNC_VERSION_LINE=rsync  version 3.2.7  protocol version 31\n"
)


class FakeRun:
    """subprocess.runの代わりに注入する、コマンド内容だけを見て応答を返すフェイク。"""

    def __init__(self, *, remote_facts_stdout: bytes, local_rsync_version: bytes = b"rsync  version 3.5.0  protocol version 32\n"):
        self.calls: list[tuple[list[str], dict]] = []
        self.remote_facts_stdout = remote_facts_stdout
        self.local_rsync_version = local_rsync_version
        self.facts_stdout = b""
        self.digest_stdout = b""
        self.ensure_directories_result = completed(0)
        self.send_result = completed(0, stdout=b">f+++++++++ a.arw\n")

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0].endswith("rsync") and "--version" in command:
            return completed(0, stdout=self.local_rsync_version)
        if command[0].endswith("rsync"):
            return self.send_result
        if "-O" in command or "-M" in command:
            return completed(0)
        # facts()とdigest()はスクリプトを`bash -c`の引数として渡し、標準入力はデータ専用にする。
        if "sha256sum" in command[-1]:
            return completed(0, stdout=self.digest_stdout)
        if "while IFS=" in command[-1]:
            if self.facts_stdout:
                return completed(0, stdout=self.facts_stdout)
            return completed(0, stdout=b"".join(b"missing\0" + path + b"\0" for path in kwargs.get("input", b"").split(b"\0") if path))
        input_bytes = kwargs.get("input", b"")
        if input_bytes == _PREFLIGHT_FACTS_SCRIPT.encode():
            return completed(0, stdout=self.remote_facts_stdout)
        if input_bytes == _ENSURE_DIRECTORIES_SCRIPT.encode():
            return self.ensure_directories_result
        raise AssertionError(f"想定しないコマンド: {command} ({kwargs})")


def make_transfer(
    run: FakeRun, destination_root: Path = Path("/mnt/camera_archive/photo-library"), **host_overrides
) -> RsyncSshTransfer:
    return RsyncSshTransfer(make_host_config(**host_overrides), destination_root, run=run, uid=999)


class PreflightTest(unittest.TestCase):
    def test_success_records_local_and_remote_versions(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        transfer.preflight()

        self.assertIn("3.5.0", transfer.local_rsync_version)
        self.assertIn("3.2.7", transfer.remote_rsync_version)

    def test_destination_root_outside_mount_is_rejected_without_ssh(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run, destination_root=Path("/mnt/other/test"))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()
        self.assertEqual(run.calls, [])

    def test_destination_root_under_mount_but_outside_library_root_is_rejected_without_ssh(self) -> None:
        """主HDD配下でもライブラリルート外（例: 旧来の年フォルダ直下）は事前検査で拒否する。"""

        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run, destination_root=Path("/mnt/camera_archive/2026"))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()
        self.assertEqual(run.calls, [])

    def test_relative_destination_root_is_rejected_without_ssh(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run, destination_root=Path("relative/path"))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()
        self.assertEqual(run.calls, [])

    def test_owner_mismatch_is_rejected(self) -> None:
        facts = VALID_FACTS.replace(b"OWNER=amane-yajima", b"OWNER=someone-else")
        transfer = make_transfer(FakeRun(remote_facts_stdout=facts))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_unmounted_is_rejected(self) -> None:
        facts = VALID_FACTS.replace(b"MOUNTED=1", b"MOUNTED=0")
        transfer = make_transfer(FakeRun(remote_facts_stdout=facts))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_uuid_mismatch_is_rejected(self) -> None:
        facts = VALID_FACTS.replace(b"UUID=0574e6d5-uuid", b"UUID=different-uuid")
        transfer = make_transfer(FakeRun(remote_facts_stdout=facts))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_not_writable_is_rejected(self) -> None:
        facts = VALID_FACTS.replace(b"DESTINATION_WRITABLE=1", b"DESTINATION_WRITABLE=0")
        transfer = make_transfer(FakeRun(remote_facts_stdout=facts))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_old_remote_rsync_is_rejected(self) -> None:
        facts = VALID_FACTS.replace(
            b"RSYNC_VERSION_LINE=rsync  version 3.2.7  protocol version 31\n",
            b"RSYNC_VERSION_LINE=rsync  version 3.2.5  protocol version 31\n",
        )
        transfer = make_transfer(FakeRun(remote_facts_stdout=facts))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_old_local_rsync_is_rejected(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS, local_rsync_version=b"rsync  version 3.1.0  protocol version 30\n")
        transfer = make_transfer(run)

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()

    def test_ssh_connection_failure_is_rejected(self) -> None:
        class FailingMasterRun(FakeRun):
            def __call__(self, command, **kwargs):
                if "-M" in command:
                    self.calls.append((command, kwargs))
                    return completed(255, stderr=b"Connection refused")
                return super().__call__(command, **kwargs)

        transfer = make_transfer(FailingMasterRun(remote_facts_stdout=VALID_FACTS))

        with self.assertRaises(TransferUnavailable):
            transfer.preflight()


class FactsTest(unittest.TestCase):
    def test_facts_reports_existing_missing_and_other(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.facts_stdout = (
            b"file:12345\0/mnt/camera_archive/a.arw\0"
            b"missing\0/mnt/camera_archive/b.arw\0"
            b"other\0/mnt/camera_archive/c.arw\0"
        )
        transfer = make_transfer(run)

        result = transfer.facts(
            [
                Path("/mnt/camera_archive/a.arw"),
                Path("/mnt/camera_archive/b.arw"),
                Path("/mnt/camera_archive/c.arw"),
            ]
        )

        self.assertEqual(result[Path("/mnt/camera_archive/a.arw")], DestinationFacts(exists=True, is_regular_file=True, size=12345))
        self.assertEqual(result[Path("/mnt/camera_archive/b.arw")], DestinationFacts(exists=False, is_regular_file=False, size=None))
        self.assertEqual(result[Path("/mnt/camera_archive/c.arw")], DestinationFacts(exists=True, is_regular_file=False, size=None))
        _, kwargs = run.calls[-1]
        self.assertEqual(
            kwargs["input"],
            b"/mnt/camera_archive/a.arw\0/mnt/camera_archive/b.arw\0/mnt/camera_archive/c.arw\0",
        )

    def test_facts_of_empty_sequence_does_not_call_ssh(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        self.assertEqual(transfer.facts([]), {})
        self.assertEqual(run.calls, [])

    def test_facts_failure_raises_transfer_unavailable(self) -> None:
        class FailingFactsRun(FakeRun):
            def __call__(self, command, **kwargs):
                if command[0] == "ssh" and "while IFS=" in command[-1] and "sha256sum" not in command[-1]:
                    self.calls.append((command, kwargs))
                    return completed(255, stderr=b"broken pipe")
                return super().__call__(command, **kwargs)

        transfer = make_transfer(FailingFactsRun(remote_facts_stdout=VALID_FACTS))

        with self.assertRaises(TransferUnavailable):
            transfer.facts([Path("/mnt/camera_archive/a.arw")])


class DigestTest(unittest.TestCase):
    def test_digest_returns_sha256_per_path(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.digest_stdout = (
            b"deadbeef\0/mnt/camera_archive/a.arw\0"
            b"\0/mnt/camera_archive/b.arw\0"
        )
        transfer = make_transfer(run)

        result = transfer.digest([Path("/mnt/camera_archive/a.arw"), Path("/mnt/camera_archive/b.arw")])

        self.assertEqual(result[Path("/mnt/camera_archive/a.arw")], "deadbeef")
        self.assertIsNone(result[Path("/mnt/camera_archive/b.arw")])

    def test_digest_of_empty_sequence_does_not_call_ssh(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        self.assertEqual(transfer.digest([]), {})
        self.assertEqual(run.calls, [])

    def test_digest_failure_raises_transfer_unavailable(self) -> None:
        class FailingDigestRun(FakeRun):
            def __call__(self, command, **kwargs):
                if command[0] == "ssh" and "sha256sum" in command[-1]:
                    self.calls.append((command, kwargs))
                    return completed(255, stderr=b"broken pipe")
                return super().__call__(command, **kwargs)

        transfer = make_transfer(FailingDigestRun(remote_facts_stdout=VALID_FACTS))

        with self.assertRaises(TransferUnavailable):
            transfer.digest([Path("/mnt/camera_archive/a.arw")])


class EnsureDirectoriesTest(unittest.TestCase):
    def test_ensure_directories_passes_paths_positionally(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        transfer.ensure_directories([Path("/mnt/camera_archive/2026/2026-09/camera")])

        command, kwargs = run.calls[-1]
        self.assertIn("/mnt/camera_archive/2026/2026-09/camera", command[-1])
        self.assertEqual(kwargs["input"], _ENSURE_DIRECTORIES_SCRIPT.encode())

    def test_ensure_directories_of_empty_sequence_does_not_call_ssh(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        transfer.ensure_directories([])

        self.assertEqual(run.calls, [])

    def test_ensure_directories_failure_raises_transfer_unavailable(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.ensure_directories_result = completed(1, stderr=b"mkdir failed")
        transfer = make_transfer(run)

        with self.assertRaises(TransferUnavailable):
            transfer.ensure_directories([Path("/mnt/camera_archive/2026")])


class SendTest(unittest.TestCase):
    def test_copied_when_itemize_output_present(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.send_result = completed(0, stdout=b">f+++++++++ a.arw\n")
        transfer = make_transfer(run)

        outcome = transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

        self.assertIs(outcome, SendOutcome.COPIED)

    def test_existing_when_exit_zero_with_empty_output(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.send_result = completed(0, stdout=b"")
        transfer = make_transfer(run)

        outcome = transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

        self.assertIs(outcome, SendOutcome.EXISTING)

    def test_exit_23_raises_transfer_failed_not_aborted(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.send_result = completed(23, stderr=b"rsync error")
        transfer = make_transfer(run)

        with self.assertRaises(TransferFailed):
            transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

    def test_exit_24_raises_transfer_failed_not_aborted(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.send_result = completed(24, stderr=b"vanished")
        transfer = make_transfer(run)

        with self.assertRaises(TransferFailed):
            transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

    def test_other_exit_code_raises_transfer_aborted(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        run.send_result = completed(255, stderr=b"connection lost")
        transfer = make_transfer(run)

        with self.assertRaises(TransferAborted):
            transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

    def test_send_does_not_use_forbidden_rsync_options(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        transfer.send(Path("/tmp/a.arw"), Path("/mnt/camera_archive/a.arw"))

        command, _ = run.calls[-1]
        forbidden = {"-a", "--delete", "--remove-source-files", "--inplace", "--partial", "-z", "-s", "--secluded-args"}
        self.assertFalse(forbidden & set(command))


class CloseTest(unittest.TestCase):
    def test_close_issues_control_exit(self) -> None:
        run = FakeRun(remote_facts_stdout=VALID_FACTS)
        transfer = make_transfer(run)

        transfer.close()

        command, _ = run.calls[-1]
        self.assertIn("-O", command)
        self.assertIn("exit", command)


class RerunViaExecuteCopyTest(unittest.TestCase):
    """段階4: rsync over SSH経由でも、内容一致による再実行のスキップが成立することを確認する。"""

    def test_second_run_skips_via_facts_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            content = b"jpeg-content"
            (source / "DSC00001.JPG").write_bytes(content)
            destination_root = Path("/mnt/camera_archive/photo-library")
            target = destination_root / "2026" / "2026-09" / "camera" / "20260911-143052_DSC00001.JPG"

            request = CopyRequest(
                source=source,
                destination_root=destination_root,
                transfer_kind=TransferKind.RSYNC_SSH,
                year_month="2026-09",
                device=Device.CAMERA,
            )
            timestamps_for = lambda paths: {p: "20260911-143052" for p in paths}  # noqa: E731

            # 1回目: 配置先が何も存在しないので転送する。
            first_run = FakeRun(remote_facts_stdout=VALID_FACTS)
            first_transfer = make_transfer(first_run, destination_root=destination_root)
            first = execute_copy(request, timestamps_for=timestamps_for, transfer=first_transfer)
            self.assertEqual(first.counts()["copied"], 1)

            # 2回目: リモートに同じサイズ・同じSHA-256のファイルが既にあると応答する。
            digest = hashlib.sha256(content).hexdigest()
            second_run = FakeRun(remote_facts_stdout=VALID_FACTS)
            second_run.facts_stdout = f"file:{len(content)}\0{target}\0".encode()
            second_run.digest_stdout = f"{digest}\0{target}\0".encode()
            second_transfer = make_transfer(second_run, destination_root=destination_root)
            second = execute_copy(request, timestamps_for=timestamps_for, transfer=second_transfer)

            self.assertEqual(second.counts()["skipped"], 1)
            self.assertEqual(second.counts()["copied"], 0)
            # スキップと確定したのでsend()（rsync呼び出し）は行わない。
            rsync_calls = [call for call, _ in second_run.calls if call and call[0].endswith("rsync") and "--version" not in call]
            self.assertEqual(rsync_calls, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
