import argparse
import tempfile
import unittest
from pathlib import Path

from photo_manager.config import apply_cli_overrides, load_config
from photo_manager.runtime import UsageError


CONFIG = """[dest]
root = /archive
volume_uuid = archive-uuid
subdir = Photos
[source]
root = /card
[mirror]
root = /mirror
volume_uuid = mirror-uuid
[tools]
exiftool = /usr/local/bin/exiftool
[options]
hash_algorithm = sha256
free_space_margin = 1.1
eject_after_import = true
"""


class ConfigTests(unittest.TestCase):
    def write_config(self, contents=CONFIG):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "config.ini"
        path.write_text(contents)
        self.addCleanup(directory.cleanup)
        return path

    def test_loads_documented_sections_and_subdir(self):
        config = load_config(self.write_config())
        self.assertEqual(config.dest.root, Path("/archive"))
        self.assertEqual(config.dest.subdir, "Photos")
        self.assertEqual(config.hash_algorithm, "sha256")

    def test_rejects_non_sha256(self):
        with self.assertRaises(UsageError):
            load_config(self.write_config(CONFIG.replace("sha256", "blake2b")))

    def test_cli_dest_must_include_uuid(self):
        config = load_config(self.write_config())
        args = argparse.Namespace(dest=Path("/other"), dest_volume_uuid=None, source=None, no_eject=False)
        with self.assertRaises(UsageError):
            apply_cli_overrides("import", args, config)

    def test_cli_dest_pair_overrides_but_retains_subdir(self):
        config = load_config(self.write_config())
        args = argparse.Namespace(dest=Path("/other"), dest_volume_uuid="other-uuid", source=None, no_eject=False)
        effective = apply_cli_overrides("import", args, config)
        self.assertEqual(effective.dest.root, Path("/other"))
        self.assertEqual(effective.dest.volume_uuid, "other-uuid")
        self.assertEqual(effective.dest.subdir, "Photos")

    def test_mirror_requires_target_when_not_configured(self):
        config = load_config(self.write_config(CONFIG.replace("root = /mirror\nvolume_uuid = mirror-uuid\n", "")))
        args = argparse.Namespace(dest=None, dest_volume_uuid=None, to=None, to_volume_uuid=None)
        with self.assertRaises(UsageError):
            apply_cli_overrides("mirror", args, config)
