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

    def test_shared_lock_falls_back_to_a_read_only_handle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = RunResources(__import__("logging").getLogger("setup"))
            acquire_lock(root, exclusive=False, resources=resources)
            resources.cleanup()
            lock_file = root / "_photo-manager" / "import.lock"
            os.chmod(str(lock_file), 0o400)
            try:
                reader = RunResources(__import__("logging").getLogger("reader"))
                lock = acquire_lock(root, exclusive=False, resources=reader)
                self.assertEqual(lock.path, lock_file)
                reader.cleanup()

                # A writer must not silently degrade to a read-only handle.
                writer = RunResources(__import__("logging").getLogger("writer"))
                with self.assertRaises(UsageError):
                    acquire_lock(root, exclusive=True, resources=writer)
            finally:
                os.chmod(str(lock_file), 0o600)

    def test_shared_lock_refuses_to_continue_without_a_lock_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            management = root / "_photo-manager"
            management.mkdir()
            os.chmod(str(management), 0o500)
            try:
                resources = RunResources(__import__("logging").getLogger("reader"))
                with self.assertRaises(UsageError):
                    acquire_lock(root, exclusive=False, resources=resources)
            finally:
                os.chmod(str(management), 0o700)

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
