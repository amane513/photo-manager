import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from photo_manager.cli import main
from photo_manager.runtime import RunInterrupted


ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_help_is_available_for_all_commands(self):
        for name in ("photo-import", "photo-verify", "photo-mirror"):
            result = subprocess.run([str(ROOT / "scripts" / name), "--help"], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--config", result.stdout)
            if name == "photo-verify":
                self.assertNotIn("--dry-run", result.stdout)
            else:
                self.assertIn("--dry-run", result.stdout)

    def test_invalid_argument_is_usage_error(self):
        with tempfile.TemporaryDirectory() as directory:
            status = main("import", ["--not-an-option"], log_dir=Path(directory))
        self.assertEqual(status, 2)

    def test_handler_success_and_operational_error_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            self.assertEqual(main("verify", [], handler=lambda *_: 0, log_dir=log_dir), 0)
            self.assertEqual(main("verify", [], handler=lambda *_: 1, log_dir=log_dir), 1)

    def test_verbose_flag_changes_the_recorded_log_level(self):
        def emit(_args, _resources, logger):
            logger.debug("diagnostic detail")
            return 0

        with tempfile.TemporaryDirectory() as directory:
            quiet_dir = Path(directory) / "quiet"
            verbose_dir = Path(directory) / "verbose"
            self.assertEqual(main("verify", [], handler=emit, log_dir=quiet_dir), 0)
            self.assertEqual(main("verify", ["-v"], handler=emit, log_dir=verbose_dir), 0)
            quiet = "".join(path.read_text() for path in quiet_dir.glob("*.log"))
            verbose = "".join(path.read_text() for path in verbose_dir.glob("*.log"))
        self.assertNotIn("diagnostic detail", quiet)
        self.assertIn("diagnostic detail", verbose)

    def test_symlinked_script_resolves_repository_src(self):
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "photo-import"
            link.symlink_to(ROOT / "scripts" / "photo-import")
            result = subprocess.run([str(link), "--help"], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Safely manage", result.stdout)

    def test_sigterm_cleans_only_registered_destination_part_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owned = root / "destination.part"
            source_part = root / "source.part"
            owned.write_bytes(b"temporary")
            source_part.write_bytes(b"must remain")
            released = []

            def interrupted(_args, resources, _logger):
                resources.register_part_file(owned)
                resources.add_cleanup(lambda: released.append(True))
                os.kill(os.getpid(), signal.SIGTERM)
                return 0

            status = main("import", [], handler=interrupted, log_dir=root / "logs")
            self.assertEqual(status, 1)
            self.assertFalse(owned.exists())
            self.assertTrue(source_part.exists())
            self.assertEqual(released, [True])
