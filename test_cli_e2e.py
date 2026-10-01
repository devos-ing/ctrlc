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

from benchmarks.runner import _installed_cli_provenance, _verify_installed_package
from benchmarks.scoring import score_scene, validate_annotation


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

        aspect_path = self.outside / "aspect-rounding.png"
        aspect_image = Image.new("RGB", (842, 577), "#ffffff")
        ImageDraw.Draw(aspect_image).rectangle((0, 0, 303, 576), fill="#202020")
        aspect_image.save(aspect_path)
        aspect_ocr_path = self.outside / "aspect-rounding-ocr.json"
        aspect_ocr_path.write_text(json.dumps({"width": 842, "height": 577, "texts": []}))
        aspect_result = self.assert_json_success(
            self.run_cli("extract", aspect_path, "--out", self.outside / "aspect-rounding-output",
                         "--ocr-json", aspect_ocr_path, "--depth", "1"), "extract")
        aspect_measurement = json.loads(Path(aspect_result["artifacts"]["measurements"]).read_text())
        self.assertEqual(aspect_measurement["measurementVersion"], 14)
        measured_nodes = aspect_measurement["measuredScene"]["nodes"]

        def assert_source_bounds(nodes):
            for node in nodes:
                x, y, width, height = node["box"]
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertLessEqual(x + width, 842)
                self.assertLessEqual(y + height, 577)
                assert_source_bounds(node.get("children", []))

        assert_source_bounds(measured_nodes)
        self.assertTrue(any(node["box"][1] + node["box"][3] == 577 for node in measured_nodes))

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

    def test_installed_hierarchy_refinement_rendering_and_integrity_failures(self):
        image_path = self.outside / "hierarchy-source.png"
        image = Image.new("RGB", (300, 220), "#f6f6f6")
        draw = ImageDraw.Draw(image)
        draw.ellipse((60, 80, 90, 110), fill="#111111")
        draw.rectangle((115, 88, 205, 102), fill="#111111")
        image.save(image_path)
        ocr_path = self.outside / "hierarchy-ocr.json"
        ocr = {"width": 300, "height": 220, "texts": [
            {"text": "Menu", "confidence": 0.99, "box": [112, 84, 100, 22]}]}
        ocr_path.write_text(json.dumps(ocr))
        first_dir = self.outside / "depth-one"
        first = self.assert_json_success(
            self.run_cli("extract", image_path, "--out", first_dir, "--ocr-json", ocr_path,
                         "--depth", "1", "--inspector"), "extract")
        self.assertEqual(first["requestedDepth"], 1)
        self.assertEqual(first["achievedDepth"], 1)
        first_scene_path = Path(first["artifacts"]["scene"])
        first_scene = json.loads(first_scene_path.read_text())
        first_measurement_path = Path(first["artifacts"]["measurements"])
        first_measurement = json.loads(first_measurement_path.read_text())
        self.assertEqual(first_measurement["ocr"], ocr)
        measurement_hash = hashlib.sha256(json.dumps(
            first_measurement, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(first_scene["measurementArtifact"]["sha256"], measurement_hash)

        custom_scene = json.loads(json.dumps(first_scene))
        custom_scene["nodes"] = []
        for index, candidate in enumerate(first_measurement["candidates"]):
            evidence_id = candidate["evidenceId"]
            custom_scene["nodes"].append({
                "id": f"accepted-part-{index}", "type": "container", "role": "section",
                "displayName": f"Reviewed part {index}", "box": candidate["node"]["box"],
                "level": 1, "evidenceRefs": [evidence_id],
                "provenance": {"kind": "inference", "boundsMethod": "child-union",
                               "evidenceRefs": [evidence_id]}, "children": []})
        custom_scene["hierarchy"].update({"rootCount": 2, "recursiveNodeCount": 2,
                                          "achievedDepth": 1, "availableDepth": 1,
                                          "completedPasses": [1]})
        custom_scene_path = first_dir / "custom-groups.json"
        custom_scene_path.write_text(json.dumps(custom_scene))
        custom_refined = self.assert_json_success(
            self.run_cli("refine", custom_scene_path, image_path,
                         "--out", self.outside / "custom-groups-refined", "--depth", "3"),
            "refine")
        custom_scene_result = json.loads(Path(custom_refined["artifacts"]["scene"]).read_text())
        self.assertEqual([node["id"] for node in custom_scene_result["nodes"]],
                         ["accepted-part-0", "accepted-part-1"])
        self.assertEqual([node["displayName"] for node in custom_scene_result["nodes"]],
                         ["Reviewed part 0", "Reviewed part 1"])
        self.assertEqual(custom_refined["stopReason"], "no_meaningful_children")

        accepted_scene_path = first_dir / "accepted-scene.json"
        first_scene["nodes"][0]["id"] = "accepted-section"
        first_scene["nodes"][0]["displayName"] = "Reviewed section"
        accepted_scene_path.write_text(json.dumps(first_scene))
        refined_dir = self.outside / "depth-three"
        refined = self.assert_json_success(
            self.run_cli("refine", accepted_scene_path, image_path, "--out", refined_dir,
                         "--depth", "3", "--inspector"), "refine")
        self.assertEqual(refined["requestedDepth"], 3)
        self.assertEqual(refined["achievedDepth"], 3)
        self.assertEqual(refined["passesComputedThisRun"], [2, 3])
        self.assertEqual(refined["ocrInvocations"], 0)
        self.assertEqual(refined["llmCalls"], 0)
        self.assertEqual(set(refined["hierarchyPassSecondsThisRun"]), {"1", "2", "3"})
        self.assertEqual(set(refined["hierarchyPassSecondsAddedThisRun"]), {"2", "3"})
        refined_scene = json.loads(Path(refined["artifacts"]["scene"]).read_text())
        self.assertEqual(refined_scene["nodes"][0]["id"], "accepted-section")
        self.assertEqual(refined_scene["nodes"][0]["displayName"], "Reviewed section")
        self.assertEqual(refined_scene["nodes"][0]["evidenceRefs"], first_scene["nodes"][0]["evidenceRefs"])
        copied_measurement = json.loads(Path(refined["artifacts"]["measurements"]).read_text())
        self.assertEqual(hashlib.sha256(json.dumps(
            copied_measurement, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest(), measurement_hash)
        unchanged = self.assert_json_success(
            self.run_cli("refine", refined["artifacts"]["scene"], image_path,
                         "--out", self.outside / "unchanged-refine", "--depth", "3"), "refine")
        self.assertEqual(unchanged["passesComputedThisRun"], [])
        self.assertEqual(unchanged["passesAddedThisRun"], [])
        self.assertEqual(unchanged["stopReason"], "structure_unchanged")
        self.assertEqual(unchanged["hierarchyPassSecondsAddedThisRun"], {})

        accepted_component_source = json.loads(Path(first["artifacts"]["scene"]).read_text())
        accepted_component_path = Path(first["artifacts"]["scene"]).parent / "accepted-component-depth-one.json"
        accepted_component_source["nodes"][0]["id"] = "accepted-root-for-component"
        accepted_component_path.write_text(json.dumps(accepted_component_source))
        component_depth_two = self.assert_json_success(
            self.run_cli("refine", accepted_component_path, image_path,
                         "--out", self.outside / "accepted-component-depth-two", "--depth", "2"),
            "refine")
        component_scene = json.loads(Path(component_depth_two["artifacts"]["scene"]).read_text())
        self.assertTrue(component_scene["nodes"][0]["children"])
        accepted_component = component_scene["nodes"][0]["children"][0]
        accepted_component.update({"id": "accepted-component", "displayName": "Reviewed component",
                                   "provenance": {"kind": "inference", "boundsMethod": "child-union",
                                                  "evidenceRefs": accepted_component["evidenceRefs"]}})
        component_scene_path = Path(component_depth_two["artifacts"]["scene"]).parent / "accepted-component-depth-two.json"
        component_scene_path.write_text(json.dumps(component_scene))
        component_depth_three = self.assert_json_success(
            self.run_cli("refine", component_scene_path, image_path,
                         "--out", self.outside / "accepted-component-depth-three", "--depth", "3"),
            "refine")
        component_scene_three = json.loads(Path(component_depth_three["artifacts"]["scene"]).read_text())
        self.assertEqual(component_scene_three["nodes"][0]["children"][0]["id"], "accepted-component")
        self.assertEqual(component_scene_three["nodes"][0]["children"][0]["displayName"],
                         "Reviewed component")

        local_image_path = self.outside / "local-region-source.png"
        local_image = Image.new("RGB", (400, 320), "#f6f6f6")
        local_draw = ImageDraw.Draw(local_image)
        local_draw.rectangle((50, 70, 350, 210), fill="#343434")
        local_draw.rectangle((80, 100, 200, 180), fill="#f2f2f2")
        local_draw.rectangle((230, 110, 320, 160), fill="#d8d8d8")
        local_image.save(local_image_path)
        local_ocr_path = self.outside / "local-region-ocr.json"
        local_ocr = {"width": 400, "height": 320, "texts": [
            {"text": "Profile", "confidence": 0.99, "box": [105, 130, 65, 18]},
            {"text": "Save", "confidence": 0.99, "box": [250, 125, 45, 18]},
        ]}
        local_ocr_path.write_text(json.dumps(local_ocr))
        local_depth_one = self.assert_json_success(
            self.run_cli("extract", local_image_path, "--out", self.outside / "local-region-depth-one",
                         "--ocr-json", local_ocr_path, "--depth", "1"), "extract")
        local_depth_two_direct = self.assert_json_success(
            self.run_cli("extract", local_image_path, "--out", self.outside / "local-region-depth-two",
                         "--ocr-json", local_ocr_path, "--depth", "2"), "extract")

        def flatten_nodes(nodes):
            flattened = []
            for node in nodes:
                flattened.append(node)
                flattened.extend(flatten_nodes(node.get("children", [])))
            return flattened

        direct_scene = json.loads(Path(local_depth_two_direct["artifacts"]["scene"]).read_text())
        direct_local_groups = [node for node in flatten_nodes(direct_scene["nodes"])
                               if node.get("level") == 2 and any(
                                   ref.startswith("lc-") for ref in node.get("evidenceRefs", []))]
        self.assertTrue(direct_local_groups, "the measured local region should create a depth-two component")
        depth_one_scene = json.loads(Path(local_depth_one["artifacts"]["scene"]).read_text())
        depth_one_scene["nodes"][0]["displayName"] = "Reviewed local parent"
        depth_one_scene_path = Path(local_depth_one["artifacts"]["scene"]).parent / "local-region-reviewed-depth-one.json"
        depth_one_scene_path.write_text(json.dumps(depth_one_scene))
        local_refined = self.assert_json_success(
            self.run_cli("refine", depth_one_scene_path, local_image_path,
                         "--out", self.outside / "local-region-refined-depth-two", "--depth", "2"),
            "refine")
        local_refined_scene = json.loads(Path(local_refined["artifacts"]["scene"]).read_text())
        refined_local_groups = [node for node in flatten_nodes(local_refined_scene["nodes"])
                                if node.get("level") == 2 and any(
                                    ref.startswith("lc-") for ref in node.get("evidenceRefs", []))]
        self.assertEqual({node["id"] for node in refined_local_groups},
                         {node["id"] for node in direct_local_groups})
        self.assertEqual(local_refined_scene["nodes"][0]["displayName"], "Reviewed local parent")

        regroup_image_path = self.outside / "accepted-regroup-source.png"
        regroup_image = Image.new("RGB", (320, 320), "#ffffff")
        regroup_draw = ImageDraw.Draw(regroup_image)
        regroup_draw.ellipse((20, 40, 60, 80), fill="#222222")
        regroup_draw.ellipse((200, 40, 240, 80), fill="#222222")
        regroup_image.save(regroup_image_path)
        regroup_ocr_path = self.outside / "accepted-regroup-ocr.json"
        regroup_ocr = {"width": 320, "height": 320, "texts": [
            {"text": "Left", "confidence": 0.99, "box": [65, 45, 80, 25]},
            {"text": "Right", "confidence": 0.99, "box": [245, 45, 60, 25]},
        ]}
        regroup_ocr_path.write_text(json.dumps(regroup_ocr))
        regroup_depth_one = self.assert_json_success(
            self.run_cli("extract", regroup_image_path, "--out", self.outside / "accepted-regroup-depth-one",
                         "--ocr-json", regroup_ocr_path, "--depth", "1"), "extract")
        regroup_depth_two = self.assert_json_success(
            self.run_cli("refine", regroup_depth_one["artifacts"]["scene"], regroup_image_path,
                         "--out", self.outside / "accepted-regroup-depth-two", "--depth", "2"), "refine")
        regroup_scene = json.loads(Path(regroup_depth_two["artifacts"]["scene"]).read_text())
        self.assertGreaterEqual(len(regroup_scene["nodes"][0]["children"]), 2)
        regroup_measurement = json.loads(Path(regroup_depth_two["artifacts"]["measurements"]).read_text())
        member_refs = [item["evidenceId"] for item in regroup_measurement["candidates"]]
        member_boxes = [item["node"]["box"] for item in regroup_measurement["candidates"]]
        merged_box = [min(box[0] for box in member_boxes), min(box[1] for box in member_boxes),
                      max(box[0] + box[2] for box in member_boxes) - min(box[0] for box in member_boxes),
                      max(box[1] + box[3] for box in member_boxes) - min(box[1] for box in member_boxes)]
        regroup_scene["nodes"][0]["children"] = [{
            "id": "accepted-merged-row", "type": "container", "role": "component",
            "displayName": "Reviewed row", "box": merged_box, "level": 2,
            "evidenceRefs": member_refs,
            "provenance": {"kind": "inference", "boundsMethod": "child-union",
                           "evidenceRefs": member_refs}, "children": []}]
        regroup_scene["hierarchy"]["recursiveNodeCount"] = 2
        regroup_scene_path = Path(regroup_depth_two["artifacts"]["scene"]).parent / "accepted-regroup.json"
        regroup_scene_path.write_text(json.dumps(regroup_scene))
        regroup_depth_three = self.assert_json_success(
            self.run_cli("refine", regroup_scene_path, regroup_image_path,
                         "--out", self.outside / "accepted-regroup-depth-three", "--depth", "3"),
            "refine")
        regroup_scene_three = json.loads(Path(regroup_depth_three["artifacts"]["scene"]).read_text())
        regroup_children = regroup_scene_three["nodes"][0]["children"]
        self.assertEqual(len(regroup_children), 1)
        self.assertEqual(regroup_children[0]["id"], "accepted-merged-row")
        self.assertEqual(regroup_children[0]["displayName"], "Reviewed row")
        self.assertEqual(regroup_children[0]["evidenceRefs"], member_refs)
        self.assertEqual({child["id"] for child in regroup_children[0]["children"]}, set(member_refs))

        def assert_tree(nodes, parent=None):
            identities = set()
            for node in nodes:
                self.assertTrue(node["id"])
                self.assertNotIn(node["id"], identities)
                identities.add(node["id"])
                box = node["box"]
                self.assertGreater(box[2], 0)
                self.assertGreater(box[3], 0)
                if parent is not None:
                    self.assertLessEqual(parent[0], box[0])
                    self.assertLessEqual(parent[1], box[1])
                    self.assertGreaterEqual(parent[0] + parent[2], box[0] + box[2])
                    self.assertGreaterEqual(parent[1] + parent[3], box[1] + box[3])
                assert_tree(node.get("children", []), box)
        assert_tree(refined_scene["nodes"])

        html_path = self.outside / "refined-render.html"
        rendered = self.assert_json_success(
            self.run_cli("render", refined["artifacts"]["scene"], image_path,
                         "--out", html_path), "render")
        html = html_path.read_text()
        self.assertEqual(rendered["llmCalls"], 0)
        self.assertIn("Saved depth", html)
        self.assertIn("Raw candidates", html)
        self.assertIn("Measurement evidence", html)
        self.assertIn('"availableDepth":3', html)
        self.assertNotIn("__MEASUREMENTS_JSON__", html)

        malformed_nested = json.loads(json.dumps(refined_scene))
        malformed_nested["nodes"][0]["children"][0]["box"] = [0, 0, 300, 220]
        malformed_nested_path = refined_dir / "malformed-nested-scene.json"
        malformed_nested_path.write_text(json.dumps(malformed_nested))
        malformed_render = self.run_cli("render", malformed_nested_path, image_path,
                                        "--out", self.outside / "malformed-nested.html")
        self.assertEqual(malformed_render.returncode, 1)
        self.assertEqual(json.loads(malformed_render.stderr)["error"]["code"], "invalid_scene")

        process = subprocess.Popen(
            [str(self.command), "serve", refined["artifacts"]["inspector"], "--port", "0"],
            cwd=self.outside, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        try:
            ready, _, _ = select.select([process.stdout], [], [], 10)
            self.assertTrue(ready, "refined inspector did not start serving")
            response = json.loads(process.stdout.readline())
            self.assertTrue(response["ok"])
            with urllib.request.urlopen(response["result"]["url"], timeout=5) as served:
                self.assertEqual(served.status, 200)
                self.assertIn(b"Raw candidates", served.read())
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(stderr, "")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

        wrong_roi = self.run_cli("extract", image_path, "--out", self.outside / "bad-roi",
                                 "--ocr-json", ocr_path, "--depth", "1",
                                 "--roi", "300,0,300,220")
        self.assertEqual(wrong_roi.returncode, 1)
        self.assertEqual(json.loads(wrong_roi.stderr)["error"]["code"], "invalid_input")

        bad_measurement = dict(first_measurement)
        bad_measurement["roi"] = [400, 0, 300, 220]
        bad_measurement_path = first_dir / "outside-roi-measurements.json"
        bad_measurement_path.write_text(json.dumps(bad_measurement))
        bad_scene = dict(first_scene)
        bad_scene["roi"] = bad_measurement["roi"]
        bad_scene["measurementArtifact"] = {
            "path": bad_measurement_path.name,
            "sha256": hashlib.sha256(json.dumps(
                bad_measurement, ensure_ascii=False, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest(),
            "schemaVersion": 1,
        }
        bad_scene_path = first_dir / "outside-roi-scene.json"
        bad_scene_path.write_text(json.dumps(bad_scene))
        bad_refine = self.run_cli("refine", bad_scene_path, image_path,
                                  "--out", self.outside / "invalid-refine", "--depth", "3")
        self.assertEqual(bad_refine.returncode, 1)
        self.assertEqual(json.loads(bad_refine.stderr)["error"]["code"], "invalid_scene")

        mismatched_source = self.outside / "hierarchy-mismatch.png"
        Image.new("RGB", (300, 220), "#111111").save(mismatched_source)
        mismatch_refine = self.run_cli("refine", first["artifacts"]["scene"], mismatched_source,
                                       "--out", self.outside / "mismatched-refine", "--depth", "3")
        self.assertEqual(mismatch_refine.returncode, 1)
        self.assertEqual(json.loads(mismatch_refine.stderr)["error"]["code"], "source_mismatch")

        warm = self.assert_json_success(
            self.run_cli("extract", image_path, "--out", first_dir, "--ocr-json", ocr_path,
                         "--depth", "1"), "extract")
        self.assertTrue(warm["cacheHit"])
        self.assertGreater(warm["elapsedSeconds"], 0)
        self.assertEqual(warm["passesComputedThisRun"], [])
        cache_files = list((first_dir / ".cache" / "hierarchy").glob("*.json"))
        self.assertTrue(cache_files)
        self.assertIn(measurement_hash, cache_files[0].name)
        cached_scene = json.loads(cache_files[0].read_text())
        cached_scene["nodes"][0]["id"] = ""
        cache_files[0].write_text(json.dumps(cached_scene))
        malformed_cache = self.run_cli("extract", image_path, "--out", first_dir,
                                       "--ocr-json", ocr_path, "--depth", "1")
        self.assertEqual(malformed_cache.returncode, 1)
        self.assertEqual(json.loads(malformed_cache.stderr)["error"]["code"], "invalid_scene")

        benchmark_root = self.outside / "benchmark-inputs"
        annotation_dir = benchmark_root / "annotations"
        annotation_dir.mkdir(parents=True)
        annotation = {
            "version": 1,
            "source_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "width": 300,
            "height": 220,
            "roi": [0, 0, 300, 220],
            "nodes": [{"id": "menu-section", "box": [60, 80, 152, 31],
                       "level": 1, "type": "container", "parent_id": None,
                       "atomic": False, "status": "model-authored"}],
            "ignore_regions": [], "ambiguities": [], "allowed_alternatives": [],
            "annotation_provenance": {"human_verified": False},
        }
        (annotation_dir / "synthetic.json").write_text(json.dumps(annotation))
        manifest = {"version": 1, "fixtures": [{
            "id": "synthetic", "split": "tuning", "source_family": "synthetic-ui",
            "screenshot": "../hierarchy-source.png", "ocr": "../hierarchy-ocr.json",
            "annotation": "annotations/synthetic.json", "legacy_scene": None,
            "source_sha256": annotation["source_sha256"], "width": 300,
            "height": 220, "roi": [0, 0, 300, 220]}]}
        manifest_path = benchmark_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        invalid_annotation = json.loads(json.dumps(annotation))
        invalid_annotation["nodes"][0]["box"] = [290, 210, 20, 20]
        with self.assertRaisesRegex(ValueError, "outside the fixture ROI"):
            validate_annotation(invalid_annotation, manifest["fixtures"][0])
        benchmark_output = self.outside / "benchmark-output"
        benchmark_process = subprocess.run(
            [sys.executable, str(ROOT / "benchmarks" / "runner.py"),
             "--manifest", str(manifest_path), "--out", str(benchmark_output),
             "--cli", str(self.command), "--split", "tuning", "--max-depth", "1",
             "--repetitions", "2", "--no-refine-track"],
            cwd=self.outside, capture_output=True, text=True, timeout=120)
        self.assertEqual(benchmark_process.returncode, 0,
                         benchmark_process.stdout + "\n" + benchmark_process.stderr)
        self.assertTrue((benchmark_output / "result.json").is_file())
        self.assertTrue((benchmark_output / "per-screen.json").is_file())
        self.assertTrue((benchmark_output / "comparison.csv").is_file())
        self.assertTrue(list((benchmark_output / "overlays").glob("*.png")))
        self.assertTrue(list((benchmark_output / "artifacts").rglob("scene.json")))
        benchmark_result = json.loads((benchmark_output / "result.json").read_text())
        self.assertEqual(benchmark_result["screens"][0]["id"], "synthetic")
        installed_cli = benchmark_result["environment"]["installedCli"]
        self.assertEqual(installed_cli["status"], "verified")
        self.assertEqual(Path(installed_cli["interpreterExecutable"]).resolve(), self.python.resolve())
        self.assertTrue(Path(installed_cli["packageRoot"]).is_relative_to(self.environment.resolve()))
        self.assertTrue(installed_cli["entrypointRegistration"]["valid"])
        self.assertIn("hierarchy.py", installed_cli["codeHashes"])
        self.assertEqual(len(installed_cli["codeHashes"]["hierarchy.py"]), 64)
        self.assertIn("ctrlc/hierarchy.py", benchmark_result["environment"]["benchmarkCheckoutCodeHashes"])
        self.assertEqual(installed_cli["codeHashValidation"]["status"], "matched")
        self.assertIn("benchmarkRunner", benchmark_result["environment"])
        command_mode = self.command.stat().st_mode & 0o777
        setuptools_script = self.command.read_text()
        uv_script = (
            f"#!{self.python}\nimport sys\nfrom ctrlc.cli import main\n"
            "if __name__ == '__main__':\n"
            "    if sys.argv[0].endswith('-script.pyw'):\n"
            "        sys.argv[0] = sys.argv[0][:-11]\n"
            "    elif sys.argv[0].endswith('.exe'):\n"
            "        sys.argv[0] = sys.argv[0][:-4]\n"
            "    sys.exit(main())\n"
        )
        try:
            self.command.write_text(uv_script)
            self.command.chmod(command_mode)
            uv_metadata = _installed_cli_provenance(self.command, self.outside)
            self.assertEqual(uv_metadata["status"], "verified")
            self.assertTrue(uv_metadata["entrypointRegistration"]["valid"])
            _verify_installed_package(
                uv_metadata, benchmark_result["environment"]["benchmarkCheckoutCodeHashes"])
        finally:
            self.command.write_text(setuptools_script)
            self.command.chmod(command_mode)
        unknown_wrapper = self.outside / "ctrlc-unknown-wrapper"
        unknown_wrapper.write_text("#!/bin/sh\nexec true\n")
        unknown_wrapper.chmod(0o755)
        unknown_metadata = _installed_cli_provenance(unknown_wrapper, self.outside)
        self.assertEqual(unknown_metadata["status"], "unknown")
        self.assertIsNone(unknown_metadata["interpreterExecutable"])
        self.assertIsNone(unknown_metadata["codeHashes"])
        python_wrapper = self.outside / "ctrlc-python-wrapper"
        python_wrapper.write_text(
            f"#!{self.python}\nimport os, sys\n"
            f"os.execv({str(self.command)!r}, [{str(self.command)!r}, *sys.argv[1:]])\n")
        python_wrapper.chmod(0o755)
        python_wrapper_metadata = _installed_cli_provenance(python_wrapper, self.outside)
        self.assertEqual(python_wrapper_metadata["status"], "unknown")
        self.assertIsNone(python_wrapper_metadata["packageRoot"])
        with self.assertRaisesRegex(RuntimeError, "unknown CLI metadata"):
            _verify_installed_package(
                python_wrapper_metadata, benchmark_result["environment"]["benchmarkCheckoutCodeHashes"])
        altered_snapshot = dict(benchmark_result["environment"]["benchmarkCheckoutCodeHashes"])
        altered_snapshot["ctrlc/hierarchy.py"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "does not match the benchmark checkout snapshot"):
            _verify_installed_package(installed_cli, altered_snapshot)
        depth_one_row = next(row for row in benchmark_result["comparison"]
                             if row["configuration"] == "depth1")
        self.assertEqual(depth_one_row["matchedBoxCount"], 1)
        self.assertGreater(depth_one_row["matchedBoxMeanIoU"], 0.75)
        legacy_cost = next(row for row in benchmark_result["costs"]
                           if row["configuration"] == "legacy")
        self.assertEqual(legacy_cost["freshSamples"], 1)
        self.assertEqual(legacy_cost["warmSamples"], 1)

        alternative_annotation = {"nodes": [
            {"id": "a", "type": "container", "level": 1, "box": [0, 0, 100, 100],
             "parent_id": None},
            {"id": "b", "type": "container", "level": 1, "box": [10, 10, 90, 90],
             "parent_id": None},
            {"id": "c", "type": "button", "level": 2, "box": [20, 20, 20, 20],
             "parent_id": "a"}],
            "allowed_alternatives": [{"edges": [{"parent_id": "b", "child_id": "c"}]}]}
        alternative_prediction = {"nodes": [
            {"id": "pred-a", "type": "container", "level": 1, "box": [0, 0, 100, 100],
             "children": []},
            {"id": "pred-b", "type": "container", "level": 1, "box": [10, 10, 90, 90],
             "children": [{"id": "pred-c", "type": "button", "level": 2,
                           "box": [20, 20, 20, 20], "children": []}]}]}
        alternative_score = score_scene(alternative_prediction, alternative_annotation, depth=2)
        self.assertEqual(alternative_score["parentEdgeF1"]["f1"], 1.0)

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
