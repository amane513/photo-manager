"""Process-wide safety primitives shared by command implementations.

This module only cleans up files explicitly registered by this process.  It
never infers a source-card path and never removes files from a source path.
"""
from __future__ import annotations

import logging
import signal
from pathlib import Path
from typing import Callable, Dict, List


class PhotoManagerError(Exception):
    """Base class for expected command failures."""

    exit_code = 1


class UsageError(PhotoManagerError):
    """Invalid command line or configuration supplied by the user."""

    exit_code = 2


class OperationalError(PhotoManagerError):
    """A safe operation could not be completed."""

    exit_code = 1


class RunInterrupted(OperationalError):
    """SIGINT or SIGTERM was received while a command was running."""


class RunResources:
    """Own cleanup of this run's temporary destinations and resource handles."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._part_files: List[Path] = []
        self._cleanup_callbacks: List[Callable[[], None]] = []
        self._cleaned = False

    def register_part_file(self, path: Path) -> None:
        """Register only a destination-side .part created by this process."""
        if path.suffix != ".part":
            raise ValueError("only .part files may be registered for cleanup")
        self._part_files.append(path)

    def unregister_part_file(self, path: Path) -> None:
        try:
            self._part_files.remove(path)
        except ValueError:
            pass

    def add_cleanup(self, callback: Callable[[], None]) -> None:
        """Register e.g. lock release; callbacks execute in reverse order."""
        self._cleanup_callbacks.append(callback)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        for path in reversed(self._part_files):
            try:
                path.unlink()
                self.logger.info("Removed interrupted temporary file: %s", path)
            except FileNotFoundError:
                pass
            except OSError:
                self.logger.exception("Could not remove temporary file: %s", path)
        for callback in reversed(self._cleanup_callbacks):
            try:
                callback()
            except Exception:  # Cleanup must not hide the original failure.
                self.logger.exception("Cleanup callback failed")


def install_signal_handlers(resources: RunResources) -> Dict[int, object]:
    """Translate termination signals into an exception handled by the CLI.

    The handler does no I/O: cleanup and log flushing happen in ``main`` where
    normal exception unwinding is safe.
    """
    def handler(signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        raise RunInterrupted("received {0}".format(name))

    return {
        signal.SIGINT: signal.signal(signal.SIGINT, handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, handler),
    }


def restore_signal_handlers(previous: Dict[int, object]) -> None:
    """Restore the caller's handlers, important when commands run in-process."""
    for signum, handler in previous.items():
        signal.signal(signum, handler)
