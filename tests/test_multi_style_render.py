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

    def test_manifest_prompt_accumulation_multi_style(self):
        from unittest.mock import MagicMock
        from pipeline.build_manifest import run_stage_manifest
        from pipeline.project_manager import DEFAULT_LLM_CONFIG, DEFAULT_DIFFUSION_PROFILES

        with open(os.path.join(self.project_dir, "config", "diffusion_profiles.json"), "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DIFFUSION_PROFILES, f, indent=2)
        with open(os.path.join(self.project_dir, "config", "llm_models.json"), "w", encoding="utf-8") as f:
            json.dump(DEFAULT_LLM_CONFIG, f, indent=2)

        # Setup minimal chunks and beats
        chunks = [{"chunk_id": "chunk_001", "text": "A dark night on a lonely road."}]
        with open(os.path.join(self.project_dir, "artifacts", "01_chunks.json"), "w", encoding="utf-8") as f:
            json.dump({"chunks": chunks}, f)

        beats = [{"chunk_id": "chunk_001", "action_beat": "Traveler walks in the shadows.", "scene_type": "landscape"}]
        with open(os.path.join(self.project_dir, "artifacts", "02_selected_beats.json"), "w", encoding="utf-8") as f:
            json.dump({"selected_beats": beats}, f)

        mock_llm = MagicMock()
        mock_llm.resolve_model.return_value = "mock-model"
        mock_llm.chat_text.return_value = "PROMPT: Charcoal sketch of lone traveler.\nNEGATIVE: "

        # 1. Synthesize prompts for Style A: Charcoal Noir
        bible_a = {
            "characters": {},
            "settings": {},
            "active_style": {
                "id": "charcoal_noir",
                "name": "Charcoal Noir",
                "description": "Expressive charcoal drawing"
            }
        }
        with open(os.path.join(self.project_dir, "artifacts", "03_visual_bible.json"), "w", encoding="utf-8") as f:
            json.dump(bible_a, f)

        m1 = run_stage_manifest(project_dir=self.project_dir, llm_client=mock_llm, llm_config=DEFAULT_LLM_CONFIG)
        b1 = m1["blocks"][0]
        self.assertIn("illustrations", b1)
        self.assertIn("Charcoal Noir", b1["illustrations"])
        self.assertEqual(b1["illustrations"]["Charcoal Noir"]["prompt"], "Charcoal sketch of lone traveler.")

        # 2. Synthesize prompts for Style B: Kodachrome without losing Style A
        mock_llm2 = MagicMock()
        mock_llm2.resolve_model.return_value = "mock-model"
        mock_llm2.chat_text.return_value = "PROMPT: Vintage Kodachrome photograph of lone traveler.\nNEGATIVE: blur"
        bible_b = {
            "characters": {},
            "settings": {},
            "active_style": {
                "id": "1970s_kodachrome",
                "name": "1970s Kodachrome",
                "description": "Warm vintage 35mm photograph"
            }
        }
        with open(os.path.join(self.project_dir, "artifacts", "03_visual_bible.json"), "w", encoding="utf-8") as f:
            json.dump(bible_b, f)

        m2 = run_stage_manifest(project_dir=self.project_dir, llm_client=mock_llm2, llm_config=DEFAULT_LLM_CONFIG)
        b2 = m2["blocks"][0]

        # Verify BOTH styles are preserved in illustrations!
        self.assertIn("Charcoal Noir", b2["illustrations"])
        self.assertIn("1970s Kodachrome", b2["illustrations"])
        self.assertEqual(b2["illustrations"]["Charcoal Noir"]["prompt"], "Charcoal sketch of lone traveler.")
        self.assertEqual(b2["illustrations"]["1970s Kodachrome"]["prompt"], "Vintage Kodachrome photograph of lone traveler.")


if __name__ == "__main__":
    unittest.main()
