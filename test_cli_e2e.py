"""Subprocess checks for the installed ctrlc command and its public workflows."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import venv

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent


class InstalledCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="ctrlc-e2e-")
        cls.work = Path(cls._temporary.name)
        cls.dist = cls.work / "dist"
        cls.dist.mkdir()
        build = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation",
             "--outdir", str(cls.dist), str(ROOT)],
            cwd=cls.work, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError(f"wheel build failed:\n{build.stdout}\n{build.stderr}")
        wheels = list(cls.dist.glob("*.whl"))
        if len(wheels) != 1:
            raise AssertionError(f"expected one wheel, found {wheels}")
        cls.environment = cls.work / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(cls.environment)
        cls.python = cls.environment / "bin" / "python"
        cls.command = cls.environment / "bin" / "ctrlc"
        install = subprocess.run(
            [str(cls.python), "-m", "pip", "install", "--no-deps", "--ignore-installed",
             str(wheels[0])],
            cwd=cls.work, capture_output=True, text=True,
        )
        if install.returncode:
            raise AssertionError(f"wheel install failed:\n{install.stdout}\n{install.stderr}")
        cls.outside = cls.work / "outside"
        cls.outside.mkdir()

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def run_cli(self, *args, cwd=None):
        return subprocess.run([str(self.command), *map(str, args)],
                              cwd=cwd or self.outside, capture_output=True, text=True)

    def assert_json_success(self, process, command):
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        payload = json.loads(process.stdout)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["command"], command)
        self.assertTrue(payload["ok"])
        return payload["result"]

    def test_installed_help_assets_extraction_and_cache(self):
        help_result = self.run_cli("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("extract", help_result.stdout)
        version_result = self.run_cli("--version")
        self.assertEqual(version_result.returncode, 0, version_result.stderr)
        self.assertIn("ctrlc", version_result.stdout)
        module_version = subprocess.run([str(self.python), "-m", "ctrlc", "--version"],
                                        cwd=self.outside, capture_output=True, text=True)
        self.assertEqual(module_version.returncode, 0, module_version.stderr)
        self.assertEqual(module_version.stdout, version_result.stdout)
        assets = subprocess.run(
            [str(self.python), "-c",
             "from importlib.resources import files; p=files('ctrlc').joinpath('assets'); "
             "assert all(p.joinpath(n).is_file() for n in "
             "('inspector.html','alpha_matte.js','vision_ocr.swift'))"],
            cwd=self.outside, capture_output=True, text=True,
        )
        self.assertEqual(assets.returncode, 0, assets.stderr)

        image_path = self.outside / "synthetic.png"
        image = Image.new("RGB", (160, 100), "#f6f6f6")
        ImageDraw.Draw(image).rounded_rectangle((20, 30, 140, 55), radius=7,
                                                fill="#dedede")
        image.save(image_path)
        ocr_path = self.outside / "ocr.json"
        ocr_path.write_text(json.dumps({
            "width": 160, "height": 100,
            "texts": [{"text": "Sign in", "confidence": 0.99,
                       "box": [45, 36, 70, 14]}],
        }))
        output = self.outside / "extracted"
        first = self.assert_json_success(
            self.run_cli("extract", image_path, "--out", output,
                         "--ocr-json", ocr_path, "--inspector"), "extract")
        self.assertFalse(first["cacheHit"])
        artifacts = first["artifacts"]
        self.assertEqual(set(artifacts), {"scene", "packet", "run", "inspector"})
        self.assertTrue(all(Path(value).is_absolute() and Path(value).is_file()
                            for value in artifacts.values()))
        self.assertEqual(json.loads(Path(artifacts["run"]).read_text())["llmCalls"], 0)
        second = self.assert_json_success(
            self.run_cli("extract", image_path, "--out", output,
                         "--ocr-json", ocr_path, "--inspector"), "extract")
        self.assertTrue(second["cacheHit"])

        api_output = self.outside / "api-extracted"
        invalid_roi_output = self.outside / "invalid-roi"
        api_check = subprocess.run(
            [str(self.python), "-c", """
import json, sys
from pathlib import Path
from ctrlc import run_extraction
image, ocr_path, output, invalid_output = map(Path, sys.argv[1:])
ocr = json.loads(ocr_path.read_text())
result = run_extraction(image, output, ocr_data=ocr)
try:
    run_extraction(image, invalid_output, roi=[-1, 0, 10, 10], ocr_data=ocr)
except ValueError:
    pass
else:
    raise AssertionError('negative ROI was accepted')
assert not invalid_output.exists()
print(json.dumps(result))
""", str(image_path), str(ocr_path), str(api_output), str(invalid_roi_output)],
            cwd=self.outside, capture_output=True, text=True,
        )
        self.assertEqual(api_check.returncode, 0, api_check.stderr)
        api_result = json.loads(api_check.stdout)
        self.assertFalse(api_result["cacheHit"])
        self.assertTrue(Path(api_result["artifacts"]["scene"]).is_absolute())

        if platform.system() == "Darwin" and shutil.which("swiftc"):
            native_output = self.outside / "native-extraction"
            native = self.assert_json_success(
                self.run_cli("extract", ROOT / "sample" / "source.png",
                             "--out", native_output), "extract")
            self.assertEqual(native["llmCalls"], 0)
            self.assertTrue(Path(native["artifacts"]["scene"]).is_file())

    def test_render_saved_scene_embeds_assets_and_preserves_evidence(self):
        scene = ROOT / "brokerage" / "reviewed-scene.json"
        screenshot = ROOT / "brokerage" / "source.png"
        evidence = [scene, ROOT / "brokerage" / "scene.json",
                    ROOT / "brokerage" / "packet.json", ROOT / "brokerage" / "run.json"]
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence}
        output = self.outside / "reviewed-inspector.html"
        result = self.assert_json_success(
            self.run_cli("render", scene, screenshot, "--out", output), "render")
        html = output.read_text()
        reviewed = json.loads(scene.read_text())
        self.assertTrue(any(node.get("displayName") in html for node in reviewed["nodes"]
                            if node.get("displayName")))
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("mattePixels", html)
        self.assertNotIn("__SCENE_JSON__", html)
        self.assertNotIn("__MATTE_JS__", html)
        self.assertIn("--el-panel: #ffffff", html)
        self.assertEqual(result["html"], str(output.resolve()))
        self.assertEqual(result["bytes"], len(html.encode()))
        self.assertEqual(result["llmCalls"], 0)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in evidence})

        legacy_output = self.outside / "legacy-inspector.html"
        legacy = subprocess.run(
            [sys.executable, str(ROOT / "render_inspector.py"), str(scene), str(screenshot),
             "--out", str(legacy_output)], cwd=self.outside, capture_output=True, text=True,
        )
        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        legacy_result = json.loads(legacy.stdout)
        self.assertEqual(set(legacy_result), {"output", "bytes", "llmCalls"})
        self.assertEqual(legacy_result["output"], str(legacy_output.resolve()))

    def test_preview_reports_ready_url_serves_only_the_document_and_stops(self):
        document = ROOT / "sample" / "inspector.html"
        process = subprocess.Popen(
            [str(self.command), "serve", str(document), "--port", "0"],
            cwd=self.outside, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 10)
            self.assertTrue(ready, "preview did not emit its startup result")
            line = process.stdout.readline()
            payload = json.loads(line)
            self.assertEqual(payload["schemaVersion"], 1)
            self.assertEqual(payload["command"], "serve")
            self.assertTrue(payload["ok"])
            result = payload["result"]
            self.assertEqual(result["document"], str(document.resolve()))
            self.assertTrue(result["url"].startswith("http://127.0.0.1:"))
            with urllib.request.urlopen(result["url"], timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(b"Screenshot component inspector", response.read())
            with self.assertRaises(urllib.error.HTTPError) as not_found:
                urllib.request.urlopen(result["url"].replace("/sample/inspector.html", "/other"),
                                       timeout=5)
            self.assertEqual(not_found.exception.code, 404)
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(stderr, "")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_argument_and_workflow_errors_are_json_and_keep_stdout_empty(self):
        invalid_arguments = self.run_cli("extract", ROOT / "sample" / "source.png")
        self.assertEqual(invalid_arguments.returncode, 2)
        self.assertEqual(invalid_arguments.stdout, "")
        argument_error = json.loads(invalid_arguments.stderr)
        self.assertEqual(argument_error["schemaVersion"], 1)
        self.assertEqual(argument_error["command"], "extract")
        self.assertFalse(argument_error["ok"])
        self.assertEqual(argument_error["error"]["code"], "invalid_arguments")

        missing = self.run_cli("render", self.outside / "missing.json",
                               ROOT / "brokerage" / "source.png",
                               "--out", self.outside / "unused.html")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stdout, "")
        self.assertEqual(json.loads(missing.stderr)["error"]["code"], "file_not_found")

        mismatch = self.outside / "mismatch.png"
        Image.new("RGB", (16, 16), "#ffffff").save(mismatch)
        wrong_source = self.run_cli("render", ROOT / "brokerage" / "reviewed-scene.json",
                                    mismatch, "--out", self.outside / "mismatch.html")
        self.assertEqual(wrong_source.returncode, 1)
        self.assertEqual(wrong_source.stdout, "")
        self.assertEqual(json.loads(wrong_source.stderr)["error"]["code"], "source_mismatch")

        malformed_scene = self.outside / "malformed-scene.json"
        malformed_scene.write_text("[]")
        bad_scene = self.run_cli("render", malformed_scene, mismatch,
                                 "--out", self.outside / "bad-scene.html")
        self.assertEqual(bad_scene.returncode, 1)
        self.assertEqual(bad_scene.stdout, "")
        self.assertEqual(json.loads(bad_scene.stderr)["error"]["code"], "invalid_scene")

        malformed_ocr = self.outside / "malformed-ocr.json"
        malformed_ocr.write_text("[]")
        bad_ocr = self.run_cli("extract", mismatch, "--out", self.outside / "bad-ocr",
                               "--ocr-json", malformed_ocr)
        self.assertEqual(bad_ocr.returncode, 1)
        self.assertEqual(bad_ocr.stdout, "")
        self.assertEqual(json.loads(bad_ocr.stderr)["error"]["code"], "invalid_ocr")

        directory_preview = self.run_cli("serve", self.outside, "--port", "0")
        self.assertEqual(directory_preview.returncode, 1)
        self.assertEqual(directory_preview.stdout, "")
        self.assertEqual(json.loads(directory_preview.stderr)["error"]["code"],
                         "invalid_preview_document")


if __name__ == "__main__":
    unittest.main()
