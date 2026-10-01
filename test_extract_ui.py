import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw
import extract_ui


class ExtractionTests(unittest.TestCase):
    def fixture(self):
        image = Image.new("RGB", (300, 250), "#f6f6f6")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((20, 80, 280, 124), radius=10, fill="#e0e0e0")
        draw.rounded_rectangle((20, 150, 280, 194), radius=10, outline="#c6c6c6", width=1)
        draw.ellipse((40, 160, 61, 183), fill="#111111")
        draw.rectangle((81, 165, 222, 178), fill="#111111")
        draw.rectangle((42, 95, 182, 108), fill="#111111")
        ocr = {"width": 300, "height": 250, "texts": [
            {"text": "hello@example.com", "box": [42, 95, 141, 14], "confidence": .99},
            {"text": "Continue with Test", "box": [81, 165, 142, 14], "confidence": .99}]}
        return image, ocr

    def test_outline_and_fill_become_controls_with_separate_icon_and_text(self):
        image, ocr = self.fixture()
        scene = extract_ui.extract(image, ocr)
        controls = [node for node in scene["nodes"] if node["type"] in ("input", "button")]
        self.assertEqual([node["type"] for node in controls], ["input", "button"])
        self.assertEqual({child["type"] for child in controls[1]["children"]}, {"text", "image"})
        style = scene["styles"][controls[1]["styleRef"]]
        self.assertIsNotNone(style["border"])
        self.assertIsNone(scene["styles"][controls[0]["children"][0]["styleRef"]]["fontSizePx"])

    def test_provider_glyph_normalization_preserves_evidence(self):
        item = {"text": "G Continue with Google", "box": [0, 0, 100, 20], "words": [
            {"text": "G", "box": [0, 0, 10, 20]},
            {"text": "Continue", "box": [20, 0, 40, 20]},
            {"text": "with", "box": [60, 0, 15, 20]},
            {"text": "Google", "box": [75, 0, 25, 20]}]}
        result = extract_ui.label(item)
        self.assertEqual(result["text"], "Continue with Google")
        self.assertEqual(result["rawText"], item["text"])
        self.assertEqual(result["box"], [20, 0, 80, 20])

    def test_compact_packet_keeps_reviewed_names_and_only_used_styles(self):
        scene = {"roi": [0, 0, 300, 250], "nodes": [
            {"id": "b1", "type": "card", "displayName": "Options promotion", "box": [0,0,100,50],
             "children": [{"id":"b1.1","type":"text","text":"Title","box":[5,5,30,10],"styleRef":"used"}]}],
             "styles": {"used":{"textColor":"#ffffff"},"unused":{"fill":"#000000"}}}
        result = extract_ui.packet(scene)
        self.assertEqual(result["nodes"][0]["displayName"], "Options promotion")
        self.assertEqual(list(result["styles"]), ["used"])

    def test_invalid_ocr_and_roi_are_rejected(self):
        with self.assertRaises(ValueError):
            extract_ui.validate_ocr({"width": 300, "height": 250,
                "texts": [{"text": "outside", "box": [290, 0, 30, 10]}]}, (300, 250))
        with self.assertRaises(Exception):
            extract_ui.parse_roi("0,0,-1,100")

    def test_cache_hit_and_content_invalidation(self):
        image, ocr = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image_path, ocr_path = root / "image.png", root / "ocr.json"
            image.save(image_path)
            ocr_path.write_text(json.dumps(ocr))
            command = [sys.executable, str(extract_ui.HERE / "extract_ui.py"), str(image_path),
                       "--ocr-json", str(ocr_path), "--out", str(root / "result")]
            def run():
                result = subprocess.run(command, check=True, capture_output=True, text=True)
                return json.loads(result.stdout)
            first, second = run(), run()
            self.assertFalse(first["cacheHit"])
            self.assertTrue(second["cacheHit"])
            self.assertEqual(second["llmCalls"], 0)
            image.putpixel((0, 0), (240, 240, 240))
            image.save(image_path)
            self.assertFalse(run()["cacheHit"])
            ocr["texts"][0]["text"] = "changed@example.com"
            ocr_path.write_text(json.dumps(ocr))
            self.assertFalse(run()["cacheHit"])


if __name__ == "__main__":
    unittest.main()
