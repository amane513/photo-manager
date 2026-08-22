"""Shared command-line entry point.

The Phase 0 commands are intentionally planning-only scaffolds.  In
particular, this module does not mount, eject, copy, rename, write to, or
delete any source-card file.  Later phases attach implementations behind the
same parser and runtime boundary.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from .logging_utils import configure_logging
from .runtime import OperationalError, PhotoManagerError, RunInterrupted, RunResources, UsageError, install_signal_handlers, restore_signal_handlers
from .config import apply_cli_overrides, load_config
from .locking import acquire_lock, acquire_mirror_locks
from .volumes import discover_source, ensure_exiftool, ensure_hard_links, ensure_writable, validate_source, validate_volume
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
    parser.add_argument("-v", "--verbose", action="store_true", help="include diagnostic details in the log")
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


def _phase1_preflight(args: argparse.Namespace, resources: RunResources, logger: logging.Logger) -> int:
    """Run Phase-1 safety checks before later phases attach data operations.

    Source-card handling is deliberately limited to directory reads.  In
    particular, this function never creates a management directory, lock, or
    probe anywhere except the verified archive volume(s).
    """
    config = apply_cli_overrides(args.command, args, load_config(args.config))
    dest_info = validate_volume(config.dest.root, config.dest.volume_uuid)
    if args.command == "import":
        source = validate_source(config.source_root, destination=config.dest.root) if config.source_root else discover_source(config.dest.root)
        logger.info("Validated read-only SD-card source: %s", source)
        ensure_exiftool(config.exiftool)
        if not getattr(args, "dry_run", False):
            ensure_writable(config.dest.root)
            ensure_hard_links(config.dest.root)
            acquire_lock(config.dest.root, exclusive=True, resources=resources)
    elif args.command == "verify":
        acquire_lock(config.dest.root, exclusive=False, resources=resources)
    else:
        assert config.mirror is not None
        mirror_info = validate_volume(config.mirror.root, config.mirror.volume_uuid)
        if dest_info.volume_uuid.casefold() == mirror_info.volume_uuid.casefold():
            raise UsageError("mirror source and destination must be different volumes")
        if not getattr(args, "dry_run", False):
            ensure_writable(config.mirror.root)
            ensure_hard_links(config.mirror.root)
            acquire_mirror_locks(((dest_info.volume_uuid, config.dest.root), (mirror_info.volume_uuid, config.mirror.root)), resources)
    logger.info("Phase-1 checks completed for %s; no source data was modified", args.command)
    raise OperationalError("{0} data operation is not implemented yet".format(args.command))


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
    logger = configure_logging(command, log_dir)
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
