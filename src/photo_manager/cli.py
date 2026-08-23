"""Shared command-line entry point.

This module owns argument parsing, logging setup, signal handling and the
translation of expected failures into the documented exit statuses.  It
performs no volume, ledger, or file operation itself: each command's
behaviour lives in its handler.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from .logging_utils import configure_logging
from .runtime import OperationalError, PhotoManagerError, RunInterrupted, RunResources, UsageError, install_signal_handlers, restore_signal_handlers
from .importer import import_handler
from .mirror import mirror_handler
from .verify import verify_handler


Handler = Callable[[argparse.Namespace, RunResources, logging.Logger], int]


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def build_parser(command: str, program: str) -> ArgumentParser:
    parser = ArgumentParser(prog=program, description="Safely manage a photo archive without modifying the SD card.")
    parser.add_argument("--config", type=Path, help="configuration file (default: ~/.config/photo-manager/config.ini)")
    if command in ("import", "mirror"):
        parser.add_argument("--dry-run", action="store_true", help="show the plan only; do not make persistent changes")
    parser.add_argument("-v", "--verbose", action="store_true", help="log DEBUG diagnostic detail as well as the normal progress lines")
    if command == "import":
        parser.add_argument("--source", type=Path, help="mounted SD-card root; never written by this tool")
        parser.add_argument("--dest", type=Path, help="archive volume mount point (requires --dest-volume-uuid)")
        parser.add_argument("--dest-volume-uuid", help="expected archive volume UUID (requires --dest)")
        parser.add_argument("--no-eject", action="store_true", help="do not eject the SD card after a fully successful import")
    elif command == "verify":
        parser.add_argument("--dest", type=Path, help="archive volume mount point (requires --dest-volume-uuid)")
        parser.add_argument("--dest-volume-uuid", help="expected archive volume UUID (requires --dest)")
        scope = parser.add_mutually_exclusive_group()
        scope.add_argument("--year", help="verify one year (YYYY)")
        scope.add_argument("--month", help="verify one month (YYYY-MM)")
    elif command == "mirror":
        parser.add_argument("--to", type=Path, help="mirror archive volume mount point (requires --to-volume-uuid)")
        parser.add_argument("--to-volume-uuid", help="expected mirror volume UUID (requires --to)")
    else:
        raise ValueError("unknown command: {0}".format(command))
    return parser


HANDLERS: Dict[str, Handler] = {
    "import": import_handler,
    "verify": verify_handler,
    "mirror": mirror_handler,
}


def main(command: str, argv: Optional[Sequence[str]] = None, program: Optional[str] = None, *, handler: Optional[Handler] = None, log_dir: Optional[Path] = None) -> int:
    """Run one command and translate expected failures to documented statuses."""
    if argv is None:
        argv = sys.argv[1:]
    if program is None:
        program = "photo-{0}".format(command)
    parser = build_parser(command, program)
    try:
        args = parser.parse_args(list(argv))
    except UsageError as exc:
        parser.print_usage(sys.stderr)
        print("{0}: error: {1}".format(program, exc), file=sys.stderr)
        return exc.exit_code

    args.command = command
    logger = configure_logging(command, log_dir, verbose=bool(getattr(args, "verbose", False)))
    resources = RunResources(logger)
    previous_signals = install_signal_handlers(resources)
    try:
        selected = handler if handler is not None else HANDLERS[command]
        status = selected(args, resources, logger)
        if status not in (0, 1, 2):
            raise OperationalError("handler returned invalid exit status: {0}".format(status))
        logger.info("Finished %s with exit status %d", command, status)
        return status
    except PhotoManagerError as exc:
        if isinstance(exc, RunInterrupted):
            logger.warning("Interrupted: %s", exc)
        else:
            logger.error("%s", exc)
        return exc.exit_code
    except KeyboardInterrupt:
        logger.warning("Interrupted by KeyboardInterrupt")
        return 1
    except Exception:
        logger.exception("Unexpected failure")
        return 1
    finally:
        resources.cleanup()
        for item in logger.handlers:
            item.flush()
        restore_signal_handlers(previous_signals)
