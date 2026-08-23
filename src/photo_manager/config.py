"""Configuration loading and command-specific overrides.

This module deliberately keeps command-line paths and their volume UUIDs as a
pair.  A path supplied on the command line is never allowed to bypass UUID
verification.
"""
from __future__ import annotations

import configparser
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .runtime import UsageError


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "photo-manager" / "config.ini"


@dataclass(frozen=True)
class ArchiveVolume:
    root: Path
    volume_uuid: str
    subdir: str = "Camera"


@dataclass(frozen=True)
class Config:
    dest: ArchiveVolume
    source_root: Optional[Path]
    mirror: Optional[ArchiveVolume]
    exiftool: Path
    hash_algorithm: str
    free_space_margin: float
    eject_after_import: bool


def _value(parser: configparser.ConfigParser, section: str, option: str, *, required: bool = False, default: Optional[str] = None) -> Optional[str]:
    value = parser.get(section, option, fallback=default)
    if value is not None:
        value = value.strip()
    if required and not value:
        raise UsageError("missing [{0}] {1}".format(section, option))
    return value or None


def _archive(parser: configparser.ConfigParser, section: str, *, required: bool, subdir: str = "Camera") -> Optional[ArchiveVolume]:
    root = _value(parser, section, "root")
    uuid = _value(parser, section, "volume_uuid")
    if required and not root:
        raise UsageError("missing [{0}] root".format(section))
    if required and not uuid:
        raise UsageError("missing [{0}] volume_uuid".format(section))
    if bool(root) != bool(uuid):
        raise UsageError("[{0}] root and volume_uuid must be specified together".format(section))
    if not root:
        return None
    configured_subdir = _value(parser, section, "subdir", default=subdir) or subdir
    relative = Path(configured_subdir)
    if relative.is_absolute() or ".." in relative.parts or configured_subdir in ("", "."):
        raise UsageError("[{0}] subdir must be a non-empty relative path".format(section))
    return ArchiveVolume(Path(root).expanduser(), uuid, configured_subdir)


def load_config(path: Optional[Path] = None) -> Config:
    """Load one INI file and validate values independent of mounted volumes."""
    config_path = (path or DEFAULT_CONFIG_PATH).expanduser()
    if not config_path.is_file():
        raise UsageError("configuration file does not exist: {0}".format(config_path))
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        raise UsageError("cannot read configuration {0}: {1}".format(config_path, exc))

    # Only the documented section and option names are accepted.  An
    # undocumented alias would silently absorb a typo or a stale spelling and
    # let the command run against a configuration the user did not intend.
    dest = _archive(parser, "dest", required=True)
    assert dest is not None
    source = _value(parser, "source", "root")
    # The mirror keeps the primary archive's role subdirectory unless it is
    # explicitly overridden: both volumes describe the same archive layout.
    mirror = _archive(parser, "mirror", required=False, subdir=dest.subdir)
    exiftool_value = _value(parser, "tools", "exiftool", required=True)
    assert exiftool_value is not None
    exiftool = Path(exiftool_value).expanduser()
    if not exiftool.is_absolute():
        raise UsageError("[tools] exiftool must be an absolute path")
    option_section = "options"
    algorithm = _value(parser, option_section, "hash_algorithm", required=True)
    if algorithm != "sha256":
        raise UsageError("hash_algorithm must be sha256")
    try:
        margin = parser.getfloat(option_section, "free_space_margin", fallback=1.1)
    except ValueError as exc:
        raise UsageError("free_space_margin must be a number: {0}".format(exc))
    if margin < 1.0:
        raise UsageError("free_space_margin must be at least 1.0")
    try:
        eject = parser.getboolean(option_section, "eject_after_import", fallback=True)
    except ValueError as exc:
        raise UsageError("eject_after_import must be true or false: {0}".format(exc))
    return Config(dest, Path(source).expanduser() if source else None, mirror, exiftool, algorithm, margin, eject)


def _cli_archive(current: ArchiveVolume, path: Optional[Path], uuid: Optional[str], flag: str) -> ArchiveVolume:
    if (path is None) != (uuid is None):
        raise UsageError("{0} and {0}-volume-uuid must be specified together".format(flag))
    if path is None:
        return current
    value = uuid.strip() if uuid else ""
    if not value:
        raise UsageError("{0}-volume-uuid must not be empty".format(flag))
    return replace(current, root=path.expanduser(), volume_uuid=value)


def apply_cli_overrides(command: str, args: object, config: Config) -> Config:
    """Return immutable effective configuration after enforcing CLI pairs."""
    dest = _cli_archive(config.dest, getattr(args, "dest", None), getattr(args, "dest_volume_uuid", None), "--dest")
    # An omitted --source retains the configured card root.  Treating its
    # argparse default (None) as an override would silently discard config.
    source_override = getattr(args, "source", None)
    source = source_override if command == "import" and source_override is not None else config.source_root
    mirror = config.mirror
    if command == "mirror":
        to = getattr(args, "to", None)
        to_uuid = getattr(args, "to_volume_uuid", None)
        if mirror is None:
            if to is None and to_uuid is None:
                raise UsageError("mirror destination is not configured; specify --to and --to-volume-uuid")
            # The subdirectory is shared with the primary archive by design.
            mirror = ArchiveVolume(Path("."), "", config.dest.subdir)
        mirror = _cli_archive(mirror, to, to_uuid, "--to")
    if command == "import" and getattr(args, "no_eject", False):
        return replace(config, dest=dest, source_root=source, mirror=mirror, eject_after_import=False)
    return replace(config, dest=dest, source_root=source, mirror=mirror)
