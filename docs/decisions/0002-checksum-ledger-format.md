# ADR 0002: checksums.tsv format

## Status

Accepted.

## Decision

`_photo-manager/checksums.tsv` is UTF-8, tab-delimited CSV (Python's
`excel-tab` dialect), LF terminated, and has **no header row**.  Each logical
record has exactly these six fields:

1. HDD-root-relative, normalized POSIX path
2. algorithm (`sha256`)
3. lowercase 64-character SHA-256 hexadecimal digest
4. decimal byte size
5. capture time as `datetime.isoformat(timespec="seconds")`
6. import time in the same seconds-precision ISO 8601 form, with a numeric
   UTC offset (for example `2026-08-22T10:12:34+09:00`)

CSV quoting is used for paths containing a tab, newline, or non-ASCII text.
`_photo-manager/`, absolute paths, traversal, and duplicate paths are invalid.

## Consequences

The file remains append-oriented and easy to inspect.  Since there is no
header, all records are data and every row is validated.  A partial final row
may be repaired only after the original is durably copied to the host log
directory; any non-final corruption is a hard failure and is not changed.
