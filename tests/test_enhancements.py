import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from pipeline.project_manager import (
    init_project,
    slugify,
    get_project_diffusion_profiles,
    update_project_diffusion_profile,
    DEFAULT_DIFFUSION_PROFILES,
    DEFAULT_LLM_CONFIG
)
from pipeline.build_manifest import run_stage_manifest
from pipeline.render_images import run_phase_2
from pipeline.compile_html import compile_manifest_to_html
from pipeline.image_client import OpenAIImageClient
from pipeline.web_server import create_app


class TestEnhancements(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.slug = "enhancement_test_story"
        self.pdir = os.path.join(self.tmpdir, self.slug)
        for subdir in ["source", "config", "artifacts", "images"]:
            os.makedirs(os.path.join(self.pdir, subdir), exist_ok=True)
        with open(os.path.join(self.pdir, "config", "diffusion_profiles.json"), "w", encoding="utf-8") as f:
            json.dump(DEFAULT_DIFFUSION_PROFILES, f, indent=2)
        with open(os.path.join(self.pdir, "config", "llm_models.json"), "w", encoding="utf-8") as f:
            json.dump(DEFAULT_LLM_CONFIG, f, indent=2)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_profiles_have_positive_prefix(self):
        for name, profile in DEFAULT_DIFFUSION_PROFILES.get("profiles", {}).items():
            self.assertIn("positive_prefix", profile, f"Profile '{name}' missing 'positive_prefix'")

    def test_krea2_and_zit_profiles_exist_and_configured(self):
        profiles = DEFAULT_DIFFUSION_PROFILES.get("profiles", {})
        self.assertIn("krea2", profiles)
        self.assertIn("zit", profiles)

        for name in ["krea2", "zit"]:
            prof = profiles[name]
            self.assertIn("aspect_ratios", prof)
            self.assertIn("landscape", prof["aspect_ratios"])
            self.assertIn("portrait", prof["aspect_ratios"])
            self.assertIn("square", prof["aspect_ratios"])
            self.assertIn("system_prompt", prof)
            self.assertTrue(len(prof["system_prompt"]) > 20)
            self.assertIn("positive_prefix", prof)
            self.assertIn("default_negative", prof)

    def test_update_and_get_diffusion_profile_positive_prefix(self):
        profiles = get_project_diffusion_profiles(self.pdir)
        self.assertIn("positive_prefix", profiles["sdxl_base"])

        update_project_diffusion_profile(
            self.pdir,
            "sdxl_base",
            {"positive_prefix": "masterpiece, 8k uhd, cinematic lighting"}
        )
        updated = get_project_diffusion_profiles(self.pdir)
        self.assertEqual(
            updated["sdxl_base"]["positive_prefix"],
            "masterpiece, 8k uhd, cinematic lighting"
        )

    @patch("pipeline.build_manifest.LMStudioClient")
    def test_manifest_synthesis_prepends_positive_prefix(self, mock_llm_cls):
        mock_llm = MagicMock()
        mock_llm.resolve_model.return_value = "test-model"
        mock_llm.chat_text.return_value = "PROMPT: a warrior standing atop a stormy fortress\nNEGATIVE: blurry, low quality"
        mock_llm_cls.return_value = mock_llm

        # Set positive prefix in profile
        update_project_diffusion_profile(
            self.pdir,
            "sdxl_base",
            {"positive_prefix": "masterpiece, best quality"}
        )

        # Setup 01_chunks.json and 02_selected_beats.json
        artifacts_dir = os.path.join(self.pdir, "artifacts")
        with open(os.path.join(artifacts_dir, "01_chunks.json"), "w", encoding="utf-8") as f:
            json.dump({
                "chunks": [
                    {"chunk_id": "chunk_000", "text": "The warrior climbed the wet stones."}
                ]
            }, f)
        with open(os.path.join(artifacts_dir, "02_selected_beats.json"), "w", encoding="utf-8") as f:
            json.dump({
                "selected_beats": [
                    {"chunk_id": "chunk_000", "visual_cue": "climbed wet stones", "intensity": 8}
                ]
            }, f)
        with open(os.path.join(artifacts_dir, "03_visual_bible.json"), "w", encoding="utf-8") as f:
            json.dump({"characters": {}, "settings": {}}, f)

        res = run_stage_manifest(self.pdir, mock_llm, DEFAULT_LLM_CONFIG)
        self.assertIn("blocks", res)
        block = res["blocks"][0]
        self.assertIsNotNone(block.get("illustration"))
        prompt = block["illustration"]["prompt"]
        self.assertTrue(
            prompt.startswith("masterpiece, best quality, a warrior"),
            f"Expected prompt to start with prefix, got: {prompt}"
        )

    def _create_mock_manifest(self):
        artifacts_dir = os.path.join(self.pdir, "artifacts")
        manifest = {
            "project": self.slug,
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": "First passage of the story.",
                    "illustration": {
                        "prompt": "Ancient library with glowing books",
                        "negative_prompt": "blurry",
                        "width": 1024,
                        "height": 1024,
                        "seed": 100,
                        "status": "pending",
                        "image_file": None
                    }
                },
                {
                    "chunk_id": "chunk_001",
                    "text": "Second passage of the story.",
                    "illustration": {
                        "prompt": "Secret stone chamber beneath the library",
                        "negative_prompt": "blurry",
                        "width": 1024,
                        "height": 1024,
                        "seed": 101,
                        "status": "pending",
                        "image_file": None
                    }
                }
            ]
        }
        with open(os.path.join(artifacts_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    @patch.object(OpenAIImageClient, "check_health")
    @patch.object(OpenAIImageClient, "render")
    def test_multi_workflow_image_rendering_and_preservation(self, mock_render, mock_health):
        mock_health.return_value = {"online": True, "backend": "openai_compatible"}

        def fake_render(prompt, negative_prompt, width, height, seed, output_filepath):
            os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
            with open(output_filepath, "wb") as f:
                f.write(f"PNG_DATA_FOR_{os.path.basename(output_filepath)}_{prompt[:10]}".encode("utf-8"))
            return {"bytes_length": 32, "filepath": output_filepath}

        mock_render.side_effect = fake_render
        self._create_mock_manifest()

        # 1. Render using workflow 'sdxl_base'
        res1 = run_phase_2(
            project_dir=self.pdir,
            backend="openai_compatible",
            image_api_base="https://api.openai.com/v1",
            image_api_key="sk-test",
            workflow="sdxl_base.json"
        )
        sdxl_img0 = os.path.join(self.pdir, "images", "sdxl_base", "chunk_000.png")
        sdxl_img1 = os.path.join(self.pdir, "images", "sdxl_base", "chunk_001.png")
        self.assertTrue(os.path.isfile(sdxl_img0), "sdxl_base chunk_000.png was not created")
        self.assertTrue(os.path.isfile(sdxl_img1), "sdxl_base chunk_001.png was not created")

        with open(sdxl_img0, "rb") as f:
            sdxl_content0 = f.read()

        # Check manifest recorded illustrations[sdxl_base]
        b0 = res1["blocks"][0]
        self.assertIn("illustrations", b0)
        self.assertIn("sdxl_base", b0["illustrations"])
        self.assertEqual(b0["illustrations"]["sdxl_base"]["image_file"], "images/sdxl_base/chunk_000.png")

        # 2. Render using a DIFFERENT workflow 'flux_dev' with force_all=True
        res2 = run_phase_2(
            project_dir=self.pdir,
            backend="openai_compatible",
            image_api_base="https://api.openai.com/v1",
            image_api_key="sk-test",
            workflow="flux_dev.json",
            force_all=True
        )
        flux_img0 = os.path.join(self.pdir, "images", "flux_dev", "chunk_000.png")
        flux_img1 = os.path.join(self.pdir, "images", "flux_dev", "chunk_001.png")
        self.assertTrue(os.path.isfile(flux_img0), "flux_dev chunk_000.png was not created")
        self.assertTrue(os.path.isfile(flux_img1), "flux_dev chunk_001.png was not created")

        # CRITICAL CHECK: SDXL images MUST NOT BE DELETED!
        self.assertTrue(os.path.isfile(sdxl_img0), "sdxl_base chunk_000.png was destroyed by flux_dev run!")
        self.assertTrue(os.path.isfile(sdxl_img1), "sdxl_base chunk_001.png was destroyed by flux_dev run!")
        with open(sdxl_img0, "rb") as f:
            self.assertEqual(f.read(), sdxl_content0, "sdxl_base chunk_000.png content changed!")

        # Check manifest now preserves BOTH workflows in illustrations
        b0_after = res2["blocks"][0]
        self.assertIn("sdxl_base", b0_after["illustrations"])
        self.assertIn("flux_dev", b0_after["illustrations"])
        self.assertEqual(b0_after["illustrations"]["sdxl_base"]["image_file"], "images/sdxl_base/chunk_000.png")
        self.assertEqual(b0_after["illustrations"]["flux_dev"]["image_file"], "images/flux_dev/chunk_000.png")

    @patch.object(OpenAIImageClient, "check_health")
    @patch.object(OpenAIImageClient, "render")
    def test_mass_selection_regeneration(self, mock_render, mock_health):
        mock_health.return_value = {"online": True, "backend": "openai_compatible"}

        render_counts = {}

        def fake_render(prompt, negative_prompt, width, height, seed, output_filepath):
            cid = os.path.splitext(os.path.basename(output_filepath))[0]
            render_counts[cid] = render_counts.get(cid, 0) + 1
            os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
            with open(output_filepath, "wb") as f:
                f.write(f"RENDER_{cid}_COUNT_{render_counts[cid]}".encode("utf-8"))
            return {"bytes_length": 32, "filepath": output_filepath}

        mock_render.side_effect = fake_render
        self._create_mock_manifest()

        # First run: render both
        run_phase_2(
            project_dir=self.pdir,
            backend="openai_compatible",
            image_api_base="https://api.openai.com/v1",
            image_api_key="sk-test",
            workflow="sdxl_base"
        )
        self.assertEqual(render_counts["chunk_000"], 1)
        self.assertEqual(render_counts["chunk_001"], 1)

        # Mass regeneration: rerun ONLY chunk_001
        run_phase_2(
            project_dir=self.pdir,
            backend="openai_compatible",
            image_api_base="https://api.openai.com/v1",
            image_api_key="sk-test",
            workflow="sdxl_base",
            rerun_chunk_ids=["chunk_001"]
        )

        # chunk_000 should NOT have been re-rendered!
        self.assertEqual(render_counts["chunk_000"], 1)
        # chunk_001 should have been re-rendered
        self.assertEqual(render_counts["chunk_001"], 2)

    def test_compile_html_with_workflow_selection(self):
        self._create_mock_manifest()
        # Create dummy images in workflow subdirectories
        os.makedirs(os.path.join(self.pdir, "images", "sdxl_base"), exist_ok=True)
        os.makedirs(os.path.join(self.pdir, "images", "flux_dev"), exist_ok=True)
        with open(os.path.join(self.pdir, "images", "sdxl_base", "chunk_000.png"), "wb") as f:
            f.write(b"PNG_SDXL")
        with open(os.path.join(self.pdir, "images", "flux_dev", "chunk_000.png"), "wb") as f:
            f.write(b"PNG_FLUX")

        # Update manifest to reference both illustrations
        manifest_path = os.path.join(self.pdir, "artifacts", "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            m = json.load(f)
        m["blocks"][0]["illustrations"] = {
            "sdxl_base": {"image_file": "images/sdxl_base/chunk_000.png", "status": "completed"},
            "flux_dev": {"image_file": "images/flux_dev/chunk_000.png", "status": "completed"}
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(m, f)

        # Compile for sdxl_base
        html_sdxl = compile_manifest_to_html(m, self.pdir, embed_images=False, workflow="sdxl_base")
        self.assertIn("images/sdxl_base/chunk_000.png", html_sdxl)
        self.assertNotIn("images/flux_dev/chunk_000.png", html_sdxl)

        # Compile for flux_dev
        html_flux = compile_manifest_to_html(m, self.pdir, embed_images=False, workflow="flux_dev")
        self.assertIn("images/flux_dev/chunk_000.png", html_flux)
        self.assertNotIn("images/sdxl_base/chunk_000.png", html_flux)

    def test_story_slug_creation_sanitization(self):
        test_cases = [
            ("A New Story: The Dawn!", "a_new_story_the_dawn"),
            ("   Space & Magic (Part 1)  ", "space_magic_part_1"),
            ("SimpleSlug", "simpleslug"),
            ("Multiple---Dashes___and Spaces", "multiple_dashes_and_spaces"),
        ]
        for raw_title, expected_slug in test_cases:
            self.assertEqual(slugify(raw_title), expected_slug)

        # Test API endpoint
        app = create_app()
        client = app.test_client()
        resp = client.post("/api/projects", json={"slug": "My Cool Story! (2026)", "story_text": "Once upon a time..."})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["slug"], "my_cool_story_2026")
        self.assertTrue(os.path.isdir(data["path"]))
        # Cleanup created project
        shutil.rmtree(data["path"], ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
