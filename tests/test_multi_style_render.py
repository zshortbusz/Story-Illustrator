"""
tests/test_multi_style_render.py: Unit tests for multi-style isolated rendering and HTML/Ebook resolution.
"""

import os
import json
import shutil
import tempfile
import unittest
from pipeline.image_client import MockImageClient
from pipeline.render_images import render_block, run_phase_2
from pipeline.compile_html import find_illustration_in_block, compile_manifest_to_html
from pipeline.book_exporter import resolve_block_illustration


class TestMultiStyleRender(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "test_project")
        os.makedirs(os.path.join(self.project_dir, "artifacts"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "config"), exist_ok=True)
        self.mock_client = MockImageClient()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_render_block_style_namespacing(self):
        block = {
            "chunk_id": "chunk_001",
            "illustration": {
                "status": "pending",
                "prompt": "Scholar reading old tome in candlelit study",
                "width": 1024,
                "height": 1024
            }
        }

        # 1. Render under Charcoal Noir style
        render_block(
            image_client=self.mock_client,
            project_dir=self.project_dir,
            block=block,
            workflow_name="ZIT.json",
            workflow_slug="ZIT",
            style_name="Charcoal Noir",
            style_slug="charcoal_noir"
        )

        charcoal_img = os.path.join(self.project_dir, "images", "ZIT__charcoal_noir", "chunk_001.png")
        self.assertTrue(os.path.isfile(charcoal_img))
        self.assertIn("ZIT.json (Charcoal Noir)", block["illustrations"])
        self.assertIn("ZIT__charcoal_noir", block["illustrations"])
        self.assertEqual(block["illustrations"]["ZIT.json (Charcoal Noir)"]["status"], "completed")

        # 2. Render same workflow under 1970s Kodachrome style without overwriting charcoal
        render_block(
            image_client=self.mock_client,
            project_dir=self.project_dir,
            block=block,
            workflow_name="ZIT.json",
            workflow_slug="ZIT",
            style_name="1970s Kodachrome",
            style_slug="1970s_kodachrome"
        )

        koda_img = os.path.join(self.project_dir, "images", "ZIT__1970s_kodachrome", "chunk_001.png")
        self.assertTrue(os.path.isfile(koda_img))
        # Verify charcoal image is STILL intact on disk!
        self.assertTrue(os.path.isfile(charcoal_img))

        # Verify block contains both illustration sets
        self.assertIn("ZIT.json (Charcoal Noir)", block["illustrations"])
        self.assertIn("ZIT.json (1970s Kodachrome)", block["illustrations"])

    def test_find_illustration_in_block_composite_keys(self):
        block = {
            "chunk_id": "chunk_000",
            "illustration": {"image_file": "images/default.png", "prompt": "Default prompt"},
            "illustrations": {
                "ZIT.json (Charcoal Noir)": {
                    "image_file": "images/ZIT__charcoal_noir/chunk_000.png",
                    "prompt": "Charcoal prompt"
                },
                "ZIT.json (1970s Kodachrome)": {
                    "image_file": "images/ZIT__1970s_kodachrome/chunk_000.png",
                    "prompt": "Kodachrome prompt"
                }
            }
        }

        # Exact title match
        res1 = find_illustration_in_block(block, "ZIT.json (Charcoal Noir)")
        self.assertIsNotNone(res1)
        self.assertEqual(res1["prompt"], "Charcoal prompt")

        # Friendly name without .json
        res2 = find_illustration_in_block(block, "ZIT (Charcoal Noir)")
        self.assertIsNotNone(res2)
        self.assertEqual(res2["prompt"], "Charcoal prompt")

        # Underscore slug resolution
        res3 = find_illustration_in_block(block, "ZIT__1970s_kodachrome")
        self.assertIsNotNone(res3)
        self.assertEqual(res3["prompt"], "Kodachrome prompt")

    def test_resolve_block_illustration_in_book_exporter(self):
        # Create dummy image on disk
        img_dir = os.path.join(self.project_dir, "images", "ZIT__charcoal_noir")
        os.makedirs(img_dir, exist_ok=True)
        dummy_img = os.path.join(img_dir, "chunk_000.png")
        with open(dummy_img, "wb") as f:
            f.write(b"PNG_MOCK")

        block = {
            "chunk_id": "chunk_000",
            "illustrations": {
                "ZIT.json (Charcoal Noir)": {
                    "image_file": "images/ZIT__charcoal_noir/chunk_000.png",
                    "prompt": "Charcoal prompt"
                }
            }
        }

        res = resolve_block_illustration(block, self.project_dir, workflow="ZIT (Charcoal Noir)")
        self.assertIsNotNone(res)
        full_path, prompt, cid = res
        self.assertEqual(cid, "chunk_000")
        self.assertEqual(prompt, "Charcoal prompt")
        self.assertTrue(os.path.isfile(full_path))


if __name__ == "__main__":
    unittest.main()
