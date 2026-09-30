"""
tests/test_security_traversal.py: Security regression tests for path traversal
and arbitrary file read vulnerabilities in book exporters, compile_html, and cover manager.
"""

import os
import json
import shutil
import tempfile
import unittest
from PIL import Image

from pipeline.book_exporter import resolve_block_illustration, resolve_cover_image
from pipeline.compile_html import compile_manifest_to_html
from pipeline.cover_manager import set_existing_scene_as_cover


class TestPathTraversalSecurity(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_root, "project")
        self.outside_dir = os.path.join(self.temp_root, "outside")
        os.makedirs(self.project_dir, exist_ok=True)
        os.makedirs(self.outside_dir, exist_ok=True)

        # Place a "secret" file outside the project directory
        self.secret_file = os.path.join(self.outside_dir, "secret.txt")
        with open(self.secret_file, "w", encoding="utf-8") as f:
            f.write("SENSITIVE_DATA_DO_NOT_LEAK")

        # Place a dummy image outside
        self.secret_image = os.path.join(self.outside_dir, "secret_image.png")
        img = Image.new("RGB", (64, 64), color=(255, 0, 0))
        img.save(self.secret_image, format="PNG")

        # Legitimate project image
        self.images_dir = os.path.join(self.project_dir, "images")
        os.makedirs(self.images_dir, exist_ok=True)
        self.legit_image = os.path.join(self.images_dir, "chunk_001.png")
        img2 = Image.new("RGB", (64, 64), color=(0, 255, 0))
        img2.save(self.legit_image, format="PNG")

    def tearDown(self):
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_resolve_block_illustration_traversal_relative(self):
        """Verifies that relative path traversal (../../secret) is rejected by resolve_block_illustration."""
        rel_traversal = os.path.relpath(self.secret_image, self.project_dir)
        block = {
            "chunk_id": "chunk_001",
            "illustration": {
                "image_file": rel_traversal,
                "prompt": "Test"
            }
        }
        res = resolve_block_illustration(block, self.project_dir)
        self.assertIsNone(
            res,
            f"VULNERABILITY: resolve_block_illustration resolved traversed path {rel_traversal} -> {res}"
        )

    def test_resolve_block_illustration_traversal_absolute(self):
        """Verifies that absolute system paths (/etc/passwd, C:\\...) are rejected."""
        block = {
            "chunk_id": "chunk_001",
            "illustration": {
                "image_file": os.path.abspath(self.secret_image),
                "prompt": "Test"
            }
        }
        res = resolve_block_illustration(block, self.project_dir)
        self.assertIsNone(
            res,
            f"VULNERABILITY: resolve_block_illustration resolved absolute path -> {res}"
        )

    def test_resolve_cover_image_traversal(self):
        """Verifies that cover image resolution rejects paths escaping project directory."""
        rel_traversal = os.path.relpath(self.secret_image, self.project_dir)
        manifest = {
            "story_title": "Test",
            "cover": {
                "image_file": rel_traversal,
                "title": "Malicious Cover"
            }
        }
        res = resolve_cover_image(manifest, self.project_dir)
        self.assertIsNone(
            res,
            f"VULNERABILITY: resolve_cover_image resolved traversed path {rel_traversal} -> {res}"
        )

    def test_compile_html_traversal_rejection(self):
        """Verifies that compile_manifest_to_html refuses to read or embed files outside project_dir."""
        rel_traversal = os.path.relpath(self.secret_image, self.project_dir)
        manifest = {
            "story_title": "Test Story",
            "blocks": [
                {
                    "chunk_id": "chunk_001",
                    "text": "Secret paragraph.",
                    "illustration": {
                        "status": "completed",
                        "image_file": rel_traversal,
                        "prompt": "Leaked"
                    }
                }
            ]
        }
        # compile_manifest_to_html with embed_images=True should not embed the outside file
        html_content = compile_manifest_to_html(manifest, self.project_dir, embed_images=True)
        self.assertIsInstance(html_content, str)

        # The image should be rejected, so no illustration figure or base64 data for the secret image
        self.assertNotIn("data:image/png;base64", html_content, "VULNERABILITY: External image was base64 encoded into HTML!")


if __name__ == "__main__":
    unittest.main()
