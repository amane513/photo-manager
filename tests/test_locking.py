import fcntl
import os
import tempfile
import unittest
from pathlib import Path

from photo_manager.locking import acquire_lock, acquire_mirror_locks
from photo_manager.runtime import RunResources, UsageError


class LockingTests(unittest.TestCase):
    def test_shared_verify_locks_coexist_and_block_exclusive_import(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one = RunResources(__import__("logging").getLogger("one"))
            two = RunResources(__import__("logging").getLogger("two"))
            acquire_lock(root, exclusive=False, resources=one)
            acquire_lock(root, exclusive=False, resources=two)
            three = RunResources(__import__("logging").getLogger("three"))
            with self.assertRaises(UsageError):
                acquire_lock(root, exclusive=True, resources=three)
            one.cleanup()
            two.cleanup()

    def test_mirror_locks_are_taken_in_uuid_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left, right = root / "left", root / "right"
            left.mkdir()
            right.mkdir()
            resources = RunResources(__import__("logging").getLogger("test"))
            locks = acquire_mirror_locks((("z-uuid", left), ("a-uuid", right)), resources)
            self.assertEqual([lock.path.parent.parent for lock in locks], [right, left])
            resources.cleanup()
