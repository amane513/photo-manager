# ADR 0004: QuickTime capture time without a sidecar XML

## Status

Accepted.

## Decision

A clip's sidecar `<CreationDate>` stays the first source of truth.  When it is
missing or malformed, the QuickTime `CreateDate` is read **as UTC** and
converted to the offset reported by the `TimeZone` tag:

```python
create.replace(tzinfo=timezone.utc).astimezone(zone)
```

This was measured on a real Sony card rather than inferred:

```
$ exiftool -json -CreateDate -TimeZone .../CLIP/C0001.MP4
  "CreateDate": "2026:08:18 11:22:20",
  "TimeZone": "+09:00"

$ grep CreationDate .../CLIP/C0001M01.XML
  CreationDate value="2026-08-18T20:22:20+09:00"
```

The naive `CreateDate` plus the offset reproduces the XML value exactly, which
confirms the import specification ("MP4 の `CreateDate` はUTC保存").  Re-labelling the
UTC wall clock as local time — the previous behaviour — was nine hours early
in JST and could file a clip under the wrong day, month, and year folder.

Three secondary cases are fixed with it:

1. If exiftool already resolved an offset itself (for example under
   `-api QuickTimeUTC`, which converts using the *importing Mac's* timezone),
   that offset is honoured, not discarded: the value is converted to the
   `TimeZone` offset, preserving the instant.
2. An offset that disagrees with `TimeZone` is therefore not a failure.  The
   instant is already pinned by the offset, and `TimeZone` decides only the
   local rendering, so the conversion is exact rather than a guess.
3. If either tag is absent or unparsable, no interpretation is attempted and
   the documented step-3 file-modification-time fallback applies, including
   when `CreateDate` carries an offset but `TimeZone` was not emitted.

## Consequences

A clip with a valid sidecar XML, a broken one, and none at all now yield the
same capture time, so a corrupt XML no longer moves a file between month
folders.  Capture times keep their recorded local wall clock and offset, and
`Camera/YYYY/YYYY-MM/` is derived from that local time, never from UTC.  The
mtime fallback remains a last resort and is still the recording *end* time,
which is why it is used only when the pair of tags cannot be interpreted.
