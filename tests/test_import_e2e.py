"""End-to-end import tests that run discovery -> ledger without mocking plans.

Every other import test replaces ``_build_plans``.  These drive the real
discovery, metadata, naming, transfer and ledger path over a small fake card,
replacing only the exiftool invocation, which is injected explicitly rather
than patched onto an already-bound default argument.
"""
import json
import logging
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photo_manager import importer as importer_module
from photo_manager.config import ArchiveVolume, Config
from photo_manager.importer import import_handler
from photo_manager.ledger import LedgerError, load_ledger
from photo_manager.runtime import RunInterrupted, RunResources


EXIFTOOL = Path("/usr/bin/exiftool")


class FakeExiftool:
    """Answer only for the paths it was asked about, as real exiftool does."""

    def __init__(self, tags):
        self.tags = tags
        self.calls = []

    def __call__(self, command, stdout=None, stderr=None, check=False):
        self.calls.append(list(command))
        requested = [argument for argument in command[1:] if not argument.startswith("-")]
        rows = []
        for path in requested:
            row = {"SourceFile": path}
            row.update(self.tags.get(Path(path).name, {}))
            rows.append(row)
        return subprocess.CompletedProcess(command, 0, json.dumps(rows).encode("utf-8"), b"")


class _CardFixture(unittest.TestCase):
    """Shared fake card, archive and exiftool stand-in.  Holds no test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.card = self.root / "card"
        self.destination = self.root / "archive"
        self.destination.mkdir()
        self.stills = self.card / "DCIM" / "100MSDCF"
        self.clips = self.card / "PRIVATE" / "M4ROOT" / "CLIP"
        self.stills.mkdir(parents=True)
        self.clips.mkdir(parents=True)

        self.write(self.stills / "DSC00001.JPG", b"jpeg one")
        self.write(self.stills / "DSC00002.ARW", b"raw two")
        self.write(self.clips / "C0001.MP4", b"movie three")
        self.write(self.clips / "C0001M01.XML",
                   b'<NonRealTimeMeta><CreationDate value="2026-08-22T20:22:20+09:00"/></NonRealTimeMeta>')

        self.runner = FakeExiftool({
            "DSC00001.JPG": {"DateTimeOriginal": "2026:08:22 10:00:00"},
            "DSC00002.ARW": {"DateTimeOriginal": "2026:08:22 10:00:05"},
            # No usable QuickTime tags: the sidecar XML is what must decide.
            "C0001.MP4": {"CreateDate": "2026:08:22 11:22:20", "TimeZone": "+09:00"},
        })
        self.config = Config(ArchiveVolume(self.destination, "archive-uuid", "Camera"), self.card, None,
                             EXIFTOOL, "sha256", 1.0, True)
        self.args = SimpleNamespace(config=None, dry_run=False, source=None, dest=None,
                                    dest_volume_uuid=None, no_eject=False)
        self.logger = logging.getLogger("test-import-e2e")
        self.logger.handlers[:] = [logging.NullHandler()]

    def write(self, path, contents):
        path.write_bytes(contents)
        return path

    def run_import(self, *patchers, dry_run=False):
        """Run one whole import, returning (status, eject mock)."""
        self.args.dry_run = dry_run
        resources = RunResources(self.logger)
        with ExitStack() as stack:
            stack.enter_context(mock.patch("photo_manager.importer.load_config", return_value=self.config))
            stack.enter_context(mock.patch("photo_manager.importer.validate_volume"))
            stack.enter_context(mock.patch("photo_manager.importer.ensure_exiftool"))
            eject = stack.enter_context(mock.patch("photo_manager.volumes.eject_volume"))
            for patcher in patchers:
                stack.enter_context(patcher)
            try:
                status = import_handler(self.args, resources, self.logger, runner=self.runner)
            finally:
                resources.cleanup()
        return status, eject

    # The names the four seeded files must receive.  The MP4 and its sidecar
    # share the XML's local wall clock, not the UTC CreateDate.
    EXPECTED = (
        "Camera/2026/2026-08/20260822_100000_DSC00001.JPG",
        "Camera/2026/2026-08/20260822_100005_DSC00002.ARW",
        "Camera/2026/2026-08/20260822_202220_C0001.MP4",
        "Camera/2026/2026-08/20260822_202220_C0001M01.XML",
    )

    def ledger_paths(self):
        return sorted(load_ledger(self.destination))

    def archived(self, relative):
        return self.destination / Path(relative)

class ImportEndToEndTests(_CardFixture):
    def test_first_import_copies_records_and_ejects(self):
        status, eject = self.run_import()
        self.assertEqual(status, 0)
        for relative in self.EXPECTED:
            self.assertTrue(self.archived(relative).is_file(), relative)
        self.assertEqual(self.ledger_paths(), sorted(self.EXPECTED))
        self.assertEqual(self.archived(self.EXPECTED[0]).read_bytes(), b"jpeg one")
        self.assertEqual(self.archived(self.EXPECTED[2]).read_bytes(), b"movie three")
        eject.assert_called_once_with(self.card)
        # The card itself is untouched.
        self.assertEqual((self.stills / "DSC00001.JPG").read_bytes(), b"jpeg one")

    def test_reimporting_the_same_card_skips_everything_without_duplicate_records(self):
        self.assertEqual(self.run_import()[0], 0)
        before = {relative: self.archived(relative).stat().st_mtime_ns for relative in self.EXPECTED}
        ledger_bytes = (self.destination / "_photo-manager" / "checksums.tsv").read_bytes()

        status, eject = self.run_import()
        self.assertEqual(status, 0)
        self.assertEqual(self.ledger_paths(), sorted(self.EXPECTED))
        # Nothing was rewritten and no second record was appended.
        self.assertEqual((self.destination / "_photo-manager" / "checksums.tsv").read_bytes(), ledger_bytes)
        for relative, stamp in before.items():
            self.assertEqual(self.archived(relative).stat().st_mtime_ns, stamp)
        # No numbered duplicate was created next to any archived file.
        for relative in self.EXPECTED:
            suffix = Path(relative).suffix
            numbered = self.archived(relative).with_name(Path(relative).stem + "_2" + suffix)
            self.assertFalse(numbered.exists(), numbered)
        eject.assert_called_once_with(self.card)

    def test_partial_reimport_copies_only_the_new_file(self):
        self.assertEqual(self.run_import()[0], 0)
        self.write(self.stills / "DSC00003.JPG", b"jpeg four")
        self.runner.tags["DSC00003.JPG"] = {"DateTimeOriginal": "2026:08:22 10:00:09"}
        added = "Camera/2026/2026-08/20260822_100009_DSC00003.JPG"
        before = {relative: self.archived(relative).stat().st_mtime_ns for relative in self.EXPECTED}

        status, eject = self.run_import()
        self.assertEqual(status, 0)
        self.assertEqual(self.ledger_paths(), sorted(self.EXPECTED + (added,)))
        self.assertEqual(self.archived(added).read_bytes(), b"jpeg four")
        for relative, stamp in before.items():
            self.assertEqual(self.archived(relative).stat().st_mtime_ns, stamp)
        eject.assert_called_once_with(self.card)


class InterruptedLedgerRecoveryTests(_CardFixture):
    """A file published before its record must be completed by a re-run."""

    def _interrupt_before_the_first_record(self):
        original = importer_module.append_record
        state = {"first": True}

        def interrupting(*args, **kwargs):
            if state["first"]:
                state["first"] = False
                raise RunInterrupted("received SIGINT")
            return original(*args, **kwargs)

        return mock.patch("photo_manager.importer.append_record", interrupting)

    def test_a_run_interrupted_between_publish_and_record_is_completed_by_the_next_run(self):
        with self.assertRaises(RunInterrupted):
            self.run_import(self._interrupt_before_the_first_record())

        # Exactly one file was published, and it has no ledger record yet.
        published = [relative for relative in self.EXPECTED if self.archived(relative).is_file()]
        self.assertEqual(len(published), 1)
        self.assertEqual(self.ledger_paths(), [])
        orphan = published[0]

        status, eject = self.run_import()
        self.assertEqual(status, 0)
        # The orphan was recognised as a verified duplicate and backfilled,
        # not copied a second time under a numbered name.
        self.assertEqual(self.ledger_paths(), sorted(self.EXPECTED))
        numbered = self.archived(orphan).with_name(Path(orphan).stem + "_2" + Path(orphan).suffix)
        self.assertFalse(numbered.exists())
        eject.assert_called_once_with(self.card)

    def test_an_incomplete_backfill_is_not_reported_as_success(self):
        with self.assertRaises(RunInterrupted):
            self.run_import(self._interrupt_before_the_first_record())
        self.assertEqual(self.ledger_paths(), [])

        def refuse(*_args, **_kwargs):
            raise LedgerError("simulated supplement failure")

        status, eject = self.run_import(mock.patch("photo_manager.importer.supplement_record", refuse))
        self.assertEqual(status, 1)
        eject.assert_not_called()
