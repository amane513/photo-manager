"""全件自動検証の回帰テスト。"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from photo_copy.local import LocalTransfer
from photo_copy.models import CopyRequest, Device, TransferKind, VerificationStatus
from photo_copy.service import execute_copy
from photo_copy.transfer import DestinationFacts, TransferUnavailable
from photo_copy.verification import verify_copy


class ScenarioTransfer(LocalTransfer):
    """send完了後の検証フェーズだけを変化させる隔離用フェイク。"""

    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.send_calls = 0
        self.after_send_facts = 0

    def send(self, source, destination):
        self.send_calls += 1
        return super().send(source, destination)

    def facts(self, destinations):
        facts = super().facts(destinations)
        if not self.send_calls:
            return facts
        self.after_send_facts += 1
        if self.scenario == "missing" and self.after_send_facts == 1:
            return {path: DestinationFacts(False, False, None) for path in destinations}
        if self.scenario == "invalid" and self.after_send_facts == 1:
            return {path: DestinationFacts(True, False, None) for path in destinations}
        if self.scenario == "size-different" and self.after_send_facts == 1:
            return {path: DestinationFacts(True, True, (fact.size or 0) + 1, fact.mtime_ns) for path, fact in facts.items()}
        if self.scenario == "changed" and self.after_send_facts >= 2:
            return {path: DestinationFacts(True, True, fact.size, (fact.mtime_ns or 0) + 1) for path, fact in facts.items()}
        return facts

    def digest(self, destinations):
        if self.scenario == "different" and self.send_calls:
            return {path: hashlib.sha256(b"other").hexdigest() for path in destinations}
        if self.scenario == "unreadable-destination" and self.send_calls:
            return {path: None for path in destinations}
        if self.scenario == "interrupted" and self.send_calls:
            raise TransferUnavailable("検証時だけ接続が切れた")
        return super().digest(destinations)


class ReadOnlyFake:
    """書き込みAPIへ触れた時点で失敗する、検証API専用のフェイク。"""

    def __init__(self) -> None:
        self.local = LocalTransfer()

    def facts(self, destinations):
        return self.local.facts(destinations)

    def digest(self, destinations):
        return self.local.digest(destinations)

    def ensure_directories(self, directories):
        raise AssertionError("検証APIがensure_directoriesを呼んだ")

    def send(self, source, destination):
        raise AssertionError("検証APIがsendを呼んだ")


class VerificationTest(unittest.TestCase):
    def request(self, source: Path, destination: Path) -> CopyRequest:
        return CopyRequest(source, destination, TransferKind.LOCAL, year_month="2026-09", device=Device.CAMERA)

    def timestamps(self, paths):
        return {path: "20260911-143052" for path in paths}

    def test_new_copy_is_verified_and_manifest_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "space name.JPG").write_bytes(b"photo")
            result = execute_copy(self.request(source, root / "destination"), timestamps_for=self.timestamps)
            item = result.verification.items[0]
            self.assertIs(item.status, VerificationStatus.MATCHED)
            self.assertEqual(result.verification.totals(), (1, 5, 1, 5))
            self.assertIsNotNone(result.verification.manifest_sha256)

    def test_existing_match_reuses_hash_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "a.JPG").write_bytes(b"photo")
            request = self.request(source, root / "destination")
            execute_copy(request, timestamps_for=self.timestamps)
            calls = 0

            def digest(path):
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise AssertionError(f"検証のために再計算してはいけない: {path}")
                return hashlib.sha256(path.read_bytes()).hexdigest()

            result = execute_copy(request, timestamps_for=self.timestamps, source_digest_for=digest)
            self.assertIs(result.verification.items[0].status, VerificationStatus.MATCHED)
            # 既存一致判定自体にはコピー元のハッシュが必要である。検証のための追加呼び出しはない。
            self.assertEqual(calls, 1)

    def test_post_copy_failures_are_non_destructive(self) -> None:
        cases = {
            "missing": VerificationStatus.MISSING,
            "different": VerificationStatus.DIFFERENT,
            "size-different": VerificationStatus.DIFFERENT,
            "invalid": VerificationStatus.INVALID_DESTINATION,
            "unreadable-destination": VerificationStatus.UNREADABLE,
            "changed": VerificationStatus.DIFFERENT,
        }
        for scenario, expected in cases.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                source.mkdir()
                original = b"photo"
                (source / "a.JPG").write_bytes(original)
                transfer = ScenarioTransfer(scenario)
                result = execute_copy(self.request(source, root / "destination"), timestamps_for=self.timestamps, transfer=transfer)
                destination = result.copy.items[0].destination
                self.assertIs(result.verification.items[0].status, expected)
                self.assertEqual(transfer.send_calls, 1, "検証失敗で再転送しない")
                self.assertTrue(destination.exists(), "検証失敗でコピー済みファイルを削除しない")
                self.assertEqual((source / "a.JPG").read_bytes(), original, "コピー元を変更しない")
                self.assertIsNone(result.verification.manifest_sha256)

    def test_source_change_or_unreadable_is_not_matched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            item = source / "a.JPG"
            item.write_bytes(b"photo")
            transfer = ScenarioTransfer("normal")

            def changing_digest(path):
                value = hashlib.sha256(path.read_bytes()).hexdigest()
                path.write_bytes(b"changed")
                return value

            result = execute_copy(self.request(source, root / "destination"), timestamps_for=self.timestamps, transfer=transfer, source_digest_for=changing_digest)
            self.assertIs(result.verification.items[0].status, VerificationStatus.UNREADABLE)
            self.assertEqual(transfer.send_calls, 1)

    def test_verification_interruption_and_read_only_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "a.JPG").write_bytes(b"photo")
            interrupted = ScenarioTransfer("interrupted")
            result = execute_copy(self.request(source, root / "destination"), timestamps_for=self.timestamps, transfer=interrupted)
            self.assertFalse(result.copy.aborted)
            self.assertTrue(result.verification.not_run)
            self.assertEqual(interrupted.send_calls, 1)
            # 書き込みメソッドを備えていても、検証APIは読み取り操作だけを使う。
            clean = execute_copy(self.request(source, root / "other"), timestamps_for=self.timestamps)
            checked = verify_copy(clean.copy, transfer=ReadOnlyFake())
            self.assertTrue(checked.successful)

    def test_existing_destination_states_map_to_verification(self) -> None:
        cases = {
            "different": VerificationStatus.DIFFERENT,
            "size-different": VerificationStatus.DIFFERENT,
            "invalid": VerificationStatus.INVALID_DESTINATION,
            "source-unreadable": VerificationStatus.UNREADABLE,
            "destination-unreadable": VerificationStatus.UNREADABLE,
        }
        for scenario, expected in cases.items():
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "source"
                source.mkdir()
                original = source / "a.JPG"
                original.write_bytes(b"photo")
                request = self.request(source, root / "destination")
                initial = execute_copy(request, timestamps_for=self.timestamps)
                destination = initial.copy.items[0].destination
                if scenario == "different":
                    destination.write_bytes(b"other")
                elif scenario == "size-different":
                    destination.write_bytes(b"longer-content")
                elif scenario == "invalid":
                    destination.unlink()
                    destination.mkdir()

                class ExistingScenario(LocalTransfer):
                    def facts(self, paths):
                        if scenario == "destination-unreadable":
                            return {}
                        return super().facts(paths)

                def unreadable_digest(path):
                    if scenario == "source-unreadable":
                        raise OSError("注入した読取不能")
                    return hashlib.sha256(path.read_bytes()).hexdigest()

                transfer = ExistingScenario()
                result = execute_copy(request, timestamps_for=self.timestamps, transfer=transfer, source_digest_for=unreadable_digest)
                self.assertIs(result.verification.items[0].status, expected)
                self.assertEqual(result.counts()["copied"], 0)
                self.assertEqual(result.counts()["skipped"], 0)
                self.assertTrue(destination.exists(), "既存配置先を削除しない")
