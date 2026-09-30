"""
tests/test_exporter_edge_cases.py: Edge cases for book exporter and cover manager,
including zero-dimension image clamping, system font fallback, and EPUB XML validity.
"""

import io
import os
import shutil
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image

from pipeline.book_exporter import (
    process_image_for_epub,
    export_fxl_epub,
    export_reflowable_epub
)
from pipeline.cover_manager import get_system_font, composite_cover_typography


class TestExporterEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_process_image_extreme_aspect_ratio_banner(self):
        """Verifies downscaling a 3000x1 horizontal line does not crash with height=0."""
        img = Image.new("RGB", (3000, 1), color=(100, 100, 100))
        img_path = os.path.join(self.temp_dir, "wide.png")
        img.save(img_path, format="PNG")

        try:
            jpeg_bytes, mime = process_image_for_epub(img_path, max_dim=1600)
            self.assertEqual(mime, "image/jpeg")
            out_im = Image.open(io.BytesIO(jpeg_bytes))
            self.assertGreaterEqual(out_im.width, 1)
            self.assertGreaterEqual(out_im.height, 1)
        except ValueError as ve:
            self.fail(f"BUG REPRODUCED: process_image_for_epub crashed on zero dimension: {ve}")

    def test_process_image_extreme_aspect_ratio_sliver(self):
        """Verifies downscaling a 1x3000 vertical sliver does not crash with width=0."""
        img = Image.new("RGB", (1, 3000), color=(100, 100, 100))
        img_path = os.path.join(self.temp_dir, "tall.png")
        img.save(img_path, format="PNG")

        try:
            jpeg_bytes, mime = process_image_for_epub(img_path, max_dim=1600)
            self.assertEqual(mime, "image/jpeg")
            out_im = Image.open(io.BytesIO(jpeg_bytes))
            self.assertGreaterEqual(out_im.width, 1)
            self.assertGreaterEqual(out_im.height, 1)
        except ValueError as ve:
            self.fail(f"BUG REPRODUCED: process_image_for_epub crashed on zero dimension: {ve}")

    def test_get_system_font_fallback_scalability(self):
        """Verifies that font fallback provides a font that scales to requested size, not a 10px bitmap."""
        # Force fallback by requesting a non-existent font family and empty system paths
        from unittest.mock import patch
        with patch("os.path.isdir", return_value=False):
            font = get_system_font(font_family="nonexistent_font", bold=True, size=120)
            self.assertIsNotNone(font, "get_system_font returned None on fallback")
            bbox = font.getbbox("TITLE")
            # If it's a fixed 10px bitmap font, height will be ~10px instead of ~120px
            font_height = bbox[3] - bbox[1]
            self.assertGreaterEqual(
                font_height,
                50,
                f"BUG REPRODUCED: Fallback font is microscopic/unscaled (height={font_height}px) on a high-res cover canvas"
            )

    def test_epub_xml_control_characters_validity(self):
        """Verifies that strings containing restricted XML control characters (\\x00, \\x08, \\x0b) do not corrupt EPUB XML."""
        manifest = {
            "story_title": "Haunted\x08 Castle \"Echoes\" & Whispers",
            "metadata": {
                "title": "Haunted\x08 Castle \"Echoes\" & Whispers",
                "author": "Ghost\x00 Writer <Author>",
                "publisher": "Haunt Press & Co.",
                "description": "A spooky story with control chars \x0b and quotes \"."
            },
            "blocks": [
                {
                    "chunk_id": "chunk_001",
                    "text": "The wind howled \x0c through the corridor.",
                    "action_beat": "Ghostly wind blows",
                    "illustration": None
                }
            ]
        }
        epub_path = os.path.join(self.temp_dir, "test.epub")
        export_reflowable_epub(manifest, self.temp_dir, output_path=epub_path)

        self.assertTrue(os.path.isfile(epub_path))
        with zipfile.ZipFile(epub_path, "r") as zf:
            # Check content.opf for strict XML validity
            opf_data = zf.read("OEBPS/content.opf").decode("utf-8")
            try:
                ET.fromstring(opf_data)
            except ET.ParseError as pe:
                self.fail(f"BUG REPRODUCED: EPUB content.opf contains invalid XML: {pe}\nContent:\n{opf_data}")

            # Check story XHTML for strict XML validity
            xhtml_data = zf.read("OEBPS/Text/story.xhtml").decode("utf-8")
            try:
                ET.fromstring(xhtml_data)
            except ET.ParseError as pe:
                self.fail(f"BUG REPRODUCED: EPUB story.xhtml contains invalid XML: {pe}\nContent:\n{xhtml_data}")


if __name__ == "__main__":
    unittest.main()
