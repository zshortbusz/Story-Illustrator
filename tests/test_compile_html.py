import os
import shutil
import tempfile
import unittest
from pipeline.compile_html import (
    split_quotes,
    render_dialogue_content,
    compile_manifest_to_html,
    file_to_data_uri
)

class TestCompileHTML(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_split_quotes_dialogue(self):
        text = 'He said, "Run now!" and turned.'
        segments = split_quotes(text)
        # Should have unbolded, then bolded quotes, then unbolded
        bold_texts = [s["text"] for s in segments if s["bold"]]
        self.assertIn('"Run now!"', "".join(bold_texts))

    def test_render_dialogue_content(self):
        content = 'Kaelen whispered, "Follow me." Then paused.'
        rendered = render_dialogue_content(content)
        self.assertIn('<strong class="q">"Follow me."</strong>', rendered)

    def test_compile_manifest_to_html(self):
        manifest = {
            "story_title": "Test Odyssey",
            "active_profile": "sdxl_base",
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": 'The adventure began. "Wait," she called.',
                    "illustration": None
                }
            ]
        }
        html_out = compile_manifest_to_html(manifest, project_dir=".")
        self.assertIn("Test Odyssey", html_out)
        self.assertIn('<strong class="q">"Wait,"</strong>', html_out)
        self.assertIn("story-paragraph", html_out)
        self.assertIn("Automated Story Illustrator", html_out)

    def test_file_to_data_uri(self):
        # Non-existent file returns None
        self.assertIsNone(file_to_data_uri("non_existent_file.png"))

        # Real file returns valid data URI
        img_path = os.path.join(self.temp_dir, "test.png")
        dummy_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        with open(img_path, "wb") as f:
            f.write(dummy_png_bytes)

        data_uri = file_to_data_uri(img_path)
        self.assertIsNotNone(data_uri)
        self.assertTrue(data_uri.startswith("data:image/png;base64,"))

    def test_compile_manifest_with_embedded_image(self):
        # Create a project dir with images/chunk_001.png
        images_dir = os.path.join(self.temp_dir, "images")
        os.makedirs(images_dir, exist_ok=True)
        img_path = os.path.join(images_dir, "chunk_001.png")
        dummy_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        with open(img_path, "wb") as f:
            f.write(dummy_png_bytes)

        manifest = {
            "story_title": "Embedded Test",
            "blocks": [
                {
                    "chunk_id": "chunk_001",
                    "text": "The fortress loomed ahead.",
                    "illustration": {
                        "status": "completed",
                        "image_file": "images/chunk_001.png",
                        "prompt": "Towering obsidian fortress under stormy skies"
                    }
                }
            ]
        }

        # Test embedded mode (default)
        html_embedded = compile_manifest_to_html(manifest, project_dir=self.temp_dir, embed_images=True)
        self.assertIn("data:image/png;base64,", html_embedded)
        self.assertIn('data-filename="chunk_001.png"', html_embedded)
        self.assertIn("chunk_001.png", html_embedded)
        self.assertIn("Towering obsidian fortress", html_embedded)

        # Test linked mode (embed_images=False)
        html_linked = compile_manifest_to_html(manifest, project_dir=self.temp_dir, embed_images=False)
        self.assertNotIn("data:image/png;base64,", html_linked)
        self.assertIn('src="images/chunk_001.png"', html_linked)


if __name__ == "__main__":
    unittest.main()
