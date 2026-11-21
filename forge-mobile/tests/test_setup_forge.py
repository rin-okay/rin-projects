"""Regression tests for deploying the mobile bundle into an existing Forge root."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from setup_forge import BUNDLE, setup


class SetupForgeTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / "Forge Neo"
        self.extensions = self.root / "extensions"
        self.extensions.mkdir(parents=True)
        (self.root / "webui.py").touch()
        (self.root / "modules_forge").mkdir()

    def test_missing_bundle_check_install_and_repeat(self):
        self.assertEqual(setup(self.root, check=True), 1)
        self.assertEqual(list(self.extensions.iterdir()), [])
        self.assertEqual(setup(self.root), 0)
        self.assertEqual(setup(self.root, check=True), 0)
        self.assertEqual(setup(self.root), 0)
        self.assertEqual({p.name for p in self.extensions.iterdir()},
                         {"img2img-hires-fix", "forge-mobile-input-metadata"})

    def test_matching_renamed_extension_is_reused(self):
        source = BUNDLE / "img2img-hires-fix"
        current = self.extensions / "my-hires-fix"
        shutil.copytree(source, current)
        script = current / "scripts" / "img2img_hires_fix_v2.py"
        script.write_bytes(script.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        self.assertEqual(setup(self.root), 0)
        self.assertFalse((self.extensions / source.name).exists())

    def test_different_copy_is_recorded_without_overwriting(self):
        current = self.extensions / "forge-mobile-input-metadata"
        current.mkdir()
        existing = current / "local-notes.txt"
        existing.write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from the bundled"):
            setup(self.root)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep me")
        self.assertFalse((self.extensions / "img2img-hires-fix").exists())

    def test_duplicate_scripts_are_reported(self):
        source = BUNDLE / "img2img-hires-fix"
        shutil.copytree(source, self.extensions / source.name)
        shutil.copytree(source, self.extensions / "old-hires-copy")
        with self.assertRaisesRegex(ValueError, "Multiple copies"):
            setup(self.root)

    def test_install_failure_removes_partial_bundle(self):
        unrelated = self.extensions / "another-extension"
        unrelated.mkdir()
        copytree = shutil.copytree

        def fail_second(source, target, *args, **kwargs):
            if Path(target).name == "forge-mobile-input-metadata":
                raise OSError("failed to copy metadata helper")
            return copytree(source, target, *args, **kwargs)

        with patch("setup_forge.shutil.copytree", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "failed to copy"):
                setup(self.root)
        self.assertEqual(list(self.extensions.iterdir()), [unrelated])
