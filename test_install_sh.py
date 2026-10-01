"""Run the installer with isolated tool directories and real release downloads."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class InstallScriptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ctrlc-install-e2e-")
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.outside = self.work / "outside"
        self.outside.mkdir()
        self.installer = self.outside / "install.sh"
        shutil.copyfile(ROOT / "install.sh", self.installer)
        self.bin = self.work / "tool bin"
        self.env = {
            **os.environ,
            "UV_TOOL_DIR": str(self.work / "tools"),
            "UV_TOOL_BIN_DIR": str(self.bin),
            "UV_CACHE_DIR": str(self.work / "cache"),
            "UV_INSTALL_DIR": str(self.work / "uv bin"),
        }

    def run_installer(self, *, piped=False):
        return subprocess.run(
            ["/bin/sh"] if piped else ["/bin/sh", str(self.installer)],
            input=self.installer.read_text() if piped else None,
            cwd=self.outside, env=self.env, capture_output=True, text=True,
            timeout=120,
        )

    def assert_installed(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ctrlc 0.1.0", result.stdout)
        self.assertIn(f"Installed ctrlc at {self.bin / 'ctrlc'}", result.stdout)
        self.assertIn("to your PATH", result.stdout)
        rendered = self.outside / "inspector.html"
        preview = subprocess.run(
            [str(self.bin / "ctrlc"), "render",
             str(ROOT / "brokerage" / "reviewed-scene.json"),
             str(ROOT / "brokerage" / "source.png"), "--out", str(rendered)],
            cwd=self.outside, env=self.env, capture_output=True, text=True,
            timeout=30,
        )
        self.assertEqual(preview.returncode, 0, preview.stderr)
        html = rendered.read_text()
        self.assertIn("data:image/png;base64,", html)
        self.assertNotIn("__SCENE_JSON__", html)
        self.assertNotIn("__MATTE_JS__", html)

    def test_installs_and_reinstalls_release_with_existing_uv(self):
        if not shutil.which("uv"):
            self.skipTest("uv is required for the existing-uv case")
        self.assert_installed(self.run_installer())
        self.assert_installed(self.run_installer(piped=True))

    def test_bootstraps_uv_when_it_is_missing_from_path(self):
        self.env["PATH"] = "/usr/bin:/bin"
        if not shutil.which("curl", path=self.env["PATH"]):
            self.skipTest("curl is required to download uv")
        result = self.run_installer(piped=True)
        self.assertIn("Installing uv...", result.stdout)
        self.assertTrue((self.work / "uv bin" / "uv").is_file())
        self.assert_installed(result)

    def test_failed_download_does_not_report_success(self):
        if not shutil.which("uv"):
            self.skipTest("uv is required for the offline failure case")
        self.env["UV_OFFLINE"] = "1"
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.stderr, "")
        self.assertNotIn("Installed ctrlc at", result.stdout)
        self.assertFalse((self.bin / "ctrlc").exists())


if __name__ == "__main__":
    unittest.main()
