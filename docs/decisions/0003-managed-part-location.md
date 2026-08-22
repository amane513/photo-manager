# ADR 0003: managed temporary-file location

## Status

Accepted.

## Decision

Import temporary files are created only at
`_photo-manager/tmp/<final-file-name>.part`, not in the archive's configured
media subdirectory.  After reread checksum verification they are published to
the final location using a same-volume hard link, then the managed temporary
is unlinked.

## Consequences

Amazon Photos never observes incomplete files under `Camera/` (or a configured
replacement).  Recovery can identify tool-owned temporary files by their
private directory and strict filename pattern, so it never guesses that an
arbitrary user `*.part` is safe to delete.  Legacy `*.part` files below the
media tree remain untouched and are reported by verification as excluded
residue.
