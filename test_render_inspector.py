import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import render_inspector


class InspectorTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "source.png"
        Image.new("RGB", (100, 100), "#f6f6f6").save(source)
        data = {"sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "imageSize": [100, 100], "roi": [0, 0, 100, 100],
                "background": "#f6f6f6", "styles": {}, "nodes": [
                    {"id": "n1", "type": "text", "box": [10, 10, 80, 20],
                     "text": "</script><script>alert('unsafe')</script>"}]}
        scene = root / "scene.json"
        scene.write_text(json.dumps(data))
        return scene, source

    def test_embeds_source_and_keeps_ocr_content_inert(self):
        with tempfile.TemporaryDirectory() as folder:
            scene, source = self.fixture(Path(folder))
            html = render_inspector.render(scene, source, fragment=True)
            self.assertIn("data:image/png;base64,", html)
            self.assertIn("\\u003c/script>", html)
            self.assertNotIn("<script>alert('unsafe')", html)
            self.assertNotIn("__SCENE_JSON__", html)
            self.assertNotIn("__IMAGE_DATA_URL__", html)
            self.assertNotIn("__MATTE_JS__", html)
            self.assertNotIn("<!doctype", html)

    def test_rejects_wrong_screenshot(self):
        with tempfile.TemporaryDirectory() as folder:
            scene, source = self.fixture(Path(folder))
            Image.new("RGB", (100, 100), "#111111").save(source)
            with self.assertRaisesRegex(ValueError, "source hash"):
                render_inspector.render(scene, source)

    def test_standalone_has_no_remote_resources(self):
        with tempfile.TemporaryDirectory() as folder:
            scene, source = self.fixture(Path(folder))
            html = render_inspector.render(scene, source)
            self.assertIn('<meta name="viewport"', html)
            self.assertNotIn('src="http', html)
            self.assertNotIn('fetch(', html)


if __name__ == "__main__":
    unittest.main()
