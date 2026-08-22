import logging
import tempfile
import unittest
from pathlib import Path

from photo_manager.runtime import RunResources


class RuntimeTests(unittest.TestCase):
    def test_rejects_non_part_cleanup_registration(self):
        resources = RunResources(logging.getLogger("test"))
        with self.assertRaises(ValueError):
            resources.register_part_file(Path("not-temporary.jpg"))

    def test_cleanup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            part = Path(directory) / "copy.part"
            part.touch()
            resources = RunResources(logging.getLogger("test"))
            resources.register_part_file(part)
            resources.cleanup()
            resources.cleanup()
            self.assertFalse(part.exists())
