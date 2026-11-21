"""Exercise the extension updater with an actual sparse Git checkout."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import forge_extensions as updates


class ForgeExtensionUpdatesTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name)
        self.repo = self.base / "rin-projects"
        self.repo.mkdir()
        self.forge = self.base / "Forge Neo"
        self.extensions = self.forge / "extensions"
        self.extensions.mkdir(parents=True)
        (self.forge / "webui.py").touch()
        (self.forge / "modules_forge").mkdir()
        self.source = self.repo / "extensions" / "example"
        self.source.mkdir(parents=True)
        self.script = self.source / "script.py"
        self.script.write_text("first\n", encoding="utf-8")
        (self.source / "state").mkdir()
        (self.source / "state" / "dock-layout.json").write_text("upstream", encoding="utf-8")
        self.mobile = self.repo / "forge-mobile"
        self.mobile.mkdir()
        catalog = {"example": {"source": "extensions/example", "aliases": ["old-example"]}}
        (self.mobile / "forge-extensions.json").write_text(json.dumps(catalog), encoding="utf-8")
        self.git("init", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/rin-okay/rin-projects.git")
        self.commit()
        self.addCleanup(patch.stopall)
        patch.object(updates, "HERE", self.mobile).start()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "Fixture")

    def invoke(self, *args):
        with patch.object(updates.sys, "argv", ["forge_extensions.py", str(self.forge), *args]):
            return updates.main()

    def test_sparse_checkout_install_and_selection(self):
        self.git("sparse-checkout", "set", "forge-mobile")
        self.assertFalse(self.source.exists())
        self.assertEqual(self.invoke("sync"), 0)
        self.assertEqual(list(self.extensions.iterdir()), [])
        self.assertEqual(self.invoke("enable", "example"), 0)
        self.assertEqual((self.extensions / "example/script.py").read_text(), "first\n")
        self.assertFalse((self.extensions / "example/state").exists())
        self.assertEqual(self.invoke("disable", "example"), 0)
        self.assertEqual(self.invoke("sync"), 0)
        self.assertTrue((self.extensions / "example/script.py").exists())

    def test_matching_alias_is_adopted_and_updated_without_touching_state(self):
        alias = self.extensions / "old-example"
        (alias / "state").mkdir(parents=True)
        current = alias / "script.py"
        current.write_bytes(b"first\r\n")
        layout = alias / "state/dock-layout.json"
        layout.write_text("personal", encoding="utf-8")
        self.assertEqual(self.invoke("enable", "example"), 0)
        self.script.write_text("second\n", encoding="utf-8")
        self.commit()
        self.assertEqual(self.invoke("sync"), 0)
        self.assertEqual(current.read_text(), "second\n")
        self.assertEqual(layout.read_text(), "personal")
        self.assertFalse((self.extensions / "example").exists())

    def test_local_edit_leaves_entire_package_unchanged(self):
        self.assertEqual(self.invoke("enable", "example"), 0)
        installed = self.extensions / "example"
        (installed / "script.py").write_text("local", encoding="utf-8")
        self.script.write_text("upstream", encoding="utf-8")
        (self.source / "new.py").write_text("new", encoding="utf-8")
        self.commit()
        self.assertEqual(self.invoke("sync"), 1)
        self.assertEqual((installed / "script.py").read_text(), "local")
        self.assertFalse((installed / "new.py").exists())

    def test_removing_tracked_file_preserves_unmanaged_file(self):
        self.assertEqual(self.invoke("enable", "example"), 0)
        installed = self.extensions / "example"
        (installed / "other.py").write_text("local", encoding="utf-8")
        self.script.unlink()
        (self.source / "new.py").write_text("new", encoding="utf-8")
        self.commit()
        self.assertEqual(self.invoke("sync"), 0)
        self.assertFalse((installed / "script.py").exists())
        self.assertEqual((installed / "other.py").read_text(), "local")

    def test_overlay_checks_prerequisite_and_preserves_upstream(self):
        spec = {"target": "upstream", "requires": "scripts/rp.py"}
        with self.assertRaisesRegex(ValueError, "upstream extension first"):
            updates.find_target(self.extensions, "overlay", spec)
        upstream = self.extensions / "upstream"
        (upstream / "scripts").mkdir(parents=True)
        prereq = upstream / "scripts/rp.py"
        prereq.write_bytes(b"upstream")
        files, count = updates.deploy(
            updates.find_target(self.extensions, "overlay", spec), {"scripts/overlay.py": b"overlay"}, {},
        )
        self.assertEqual(set(files), {"scripts/overlay.py"})
        self.assertEqual(count, 1)
        self.assertEqual(prereq.read_bytes(), b"upstream")
