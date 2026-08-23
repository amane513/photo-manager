"""Logging setup that remains available while archive volumes are absent."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


def configure_logging(command: str, log_dir: Optional[Path] = None, *, verbose: bool = False) -> logging.Logger:
    """Create a per-run UTF-8 log under the macOS conventional log location.

    ``verbose`` lowers the threshold to DEBUG so that ``-v`` genuinely adds
    diagnostic lines rather than only appearing in the help text.
    """
    if log_dir is None:
        log_dir = Path.home() / "Library" / "Logs" / "photo-manager"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = log_dir / "{0}-{1}.log".format(command, stamp)
    path = base
    number = 2
    while path.exists():
        path = log_dir / "{0}-{1}-{2}.log".format(command, stamp, number)
        number += 1

    logger = logging.getLogger("photo_manager")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(str(path), encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.info("Started %s; log file: %s", command, path)
    logger.debug("Verbose logging is enabled; DEBUG diagnostics are included")
    return logger
