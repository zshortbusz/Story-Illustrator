import os
import json
import base64
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from pipeline.llm_client import LLMClient, LMStudioClient, load_llm_config
from pipeline.image_client import (
    BaseImageClient,
    ComfyUIImageClient,
    OpenAIImageClient,
    create_image_client
)
from pipeline.project_manager import init_project, DEFAULT_LLM_CONFIG, DEFAULT_DIFFUSION_PROFILES
from pipeline.render_images import run_phase_2, render_block
from pipeline.web_server import create_app


class TestBackendAgnosticLLM(unittest.TestCase):
    """Tests LLMClient under both LM Studio and generic OpenAI-compatible configurations."""

    def test_default_lm_studio_client(self):
        client = LLMClient()
        self.assertEqual(client.backend, "lm_studio")
        self.assertEqual(client.api_base, "http://localhost:1234/v1")
        self.assertEqual(client.api_key, "")

    @patch("requests.post")
    def test_lm_studio_sends_negative_max_tokens(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Story response", "role": "assistant"}}]
        }
        mock_post.return_value = mock_resp

        client = LLMClient(backend="lm_studio")
        with patch.object(client, "list_available_models", return_value=["test-model"]):
            res = client.chat_text([{"role": "user", "content": "Hi"}], model="test-model", max_tokens=-1)
            self.assertEqual(res, "Story response")
            payload = mock_post.call_args[1]["json"]
            self.assertEqual(payload["max_tokens"], -1)
            headers = mock_post.call_args[1]["headers"]
            self.assertNotIn("Authorization", headers)

    @patch("requests.post")
    def test_openai_compatible_omits_negative_max_tokens_and_sends_auth(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Cloud response", "role": "assistant"}}]
        }
        mock_post.return_value = mock_resp

        client = LLMClient(
            api_base="https://api.openai.com/v1",
            api_key="sk-test-key-12345",
            backend="openai_compatible",
            context_window=32768
        )
        res = client.chat_text([{"role": "user", "content": "Hello"}], model="gpt-4o", max_tokens=-1)
        self.assertEqual(res, "Cloud response")

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        headers = call_kwargs["headers"]

        # For cloud models, max_tokens should be omitted when negative
        self.assertNotIn("max_tokens", payload)
        # Auth header must be present
        self.assertEqual(headers.get("Authorization"), "Bearer sk-test-key-12345")
        # Model name should remain gpt-4o without being overridden
        self.assertEqual(payload["model"], "gpt-4o")

    def test_openai_context_window(self):
        client = LLMClient(
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
            backend="openai_compatible",
            context_window=64000
        )
        self.assertEqual(client.get_model_context_size(), 64000)

        # Default fallback for cloud models
        client2 = LLMClient(
            api_base="https://api.openai.com/v1",
            backend="openai_compatible"
        )
        self.assertEqual(client2.get_model_context_size(), 128000)


class TestBackendAgnosticImage(unittest.TestCase):
    """Tests ImageClient implementations and factory."""

    def test_factory_defaults_to_comfyui(self):
        client = create_image_client({})
        self.assertIsInstance(client, ComfyUIImageClient)
        self.assertEqual(client.host, "127.0.0.1:8188")

    def test_factory_creates_openai_image_client(self):
        config = {
            "backend": "openai_compatible",
            "openai_compatible": {
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-image-key",
                "model": "dall-e-3"
            }
        }
        client = create_image_client(config)
        self.assertIsInstance(client, OpenAIImageClient)
        self.assertEqual(client.model, "dall-e-3")
        self.assertEqual(client.api_key, "sk-image-key")

    def test_openai_dimension_resolution(self):
        client = OpenAIImageClient(model="dall-e-3")
        self.assertEqual(client._resolve_size(1344, 768), "1792x1024")  # Landscape
        self.assertEqual(client._resolve_size(768, 1344), "1024x1792")  # Portrait
        self.assertEqual(client._resolve_size(1024, 1024), "1024x1024")  # Square

        custom_client = OpenAIImageClient(model="FLUX.1-schnell")
        self.assertEqual(custom_client._resolve_size(1344, 768), "1344x768")

    @patch("requests.post")
    def test_openai_render_b64(self, mock_post):
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b64_str = base64.b64encode(fake_png).decode("ascii")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [{"b64_json": b64_str}]
        }
        mock_post.return_value = mock_resp

        client = OpenAIImageClient(
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
            model="dall-e-3"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "test.png")
            res = client.render("A magical forest", output_filepath=out_file)

            self.assertEqual(res["bytes_length"], len(fake_png))
            self.assertTrue(os.path.isfile(out_file))
            with open(out_file, "rb") as f:
                self.assertEqual(f.read(), fake_png)

    @patch("requests.get")
    @patch("requests.post")
    def test_openai_render_url(self, mock_post, mock_get):
        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post_resp.json.return_value = {
            "data": [{"url": "https://example.com/image.png"}]
        }
        mock_post.return_value = mock_post_resp

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.content = fake_png
        mock_get.return_value = mock_get_resp

        client = OpenAIImageClient(api_base="https://api.together.xyz/v1", api_key="sk-together")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "test_url.png")
            res = client.render("A cyberpunk warrior", output_filepath=out_file)

            self.assertEqual(res["bytes_length"], len(fake_png))
            self.assertTrue(os.path.isfile(out_file))
            with open(out_file, "rb") as f:
                self.assertEqual(f.read(), fake_png)


class TestPhase2BackendAgnostic(unittest.TestCase):
    """Tests Phase 2 dispatching with custom image backend."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pdir = os.path.join(self.tmpdir, "test_story")
        init_project("test_story")
        # Copy to temp dir to avoid modifying active projects
        shutil.copytree(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "projects", "test_story"),
            self.pdir
        )
        # Create dummy manifest with 1 pending illustration
        manifest = {
            "story_slug": "test_story",
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": "Once upon a time in a faraway realm.",
                    "illustration": {
                        "prompt": "An ancient castle at sunset",
                        "negative_prompt": "blurry",
                        "width": 1024,
                        "height": 1024,
                        "seed": 42,
                        "status": "pending",
                        "image_file": None
                    }
                }
            ]
        }
        os.makedirs(os.path.join(self.pdir, "artifacts"), exist_ok=True)
        with open(os.path.join(self.pdir, "artifacts", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        base_test_story = os.path.join(os.path.dirname(os.path.dirname(__file__)), "projects", "test_story")
        if os.path.isdir(base_test_story):
            shutil.rmtree(base_test_story, ignore_errors=True)

    @patch.object(OpenAIImageClient, "check_health")
    @patch.object(OpenAIImageClient, "render")
    def test_run_phase_2_with_openai_backend(self, mock_render, mock_health):
        mock_health.return_value = {"online": True, "backend": "openai_compatible"}

        fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

        def fake_render(prompt, negative_prompt, width, height, seed, output_filepath):
            os.makedirs(os.path.dirname(output_filepath), exist_ok=True)
            with open(output_filepath, "wb") as f:
                f.write(fake_png)
            return {"bytes_length": len(fake_png), "filepath": output_filepath}

        mock_render.side_effect = fake_render

        updated = run_phase_2(
            project_dir=self.pdir,
            backend="openai_compatible",
            image_api_base="https://api.openai.com/v1",
            image_api_key="sk-test",
            image_model="dall-e-3"
        )

        block = updated["blocks"][0]
        self.assertEqual(block["illustration"]["status"], "completed")
        self.assertIn("images/", block["illustration"]["image_file"])
        self.assertTrue(os.path.isfile(os.path.join(self.pdir, block["illustration"]["image_file"])))


class TestWebAPIProvidersEndpoint(unittest.TestCase):
    """Tests the REST API providers endpoint."""

    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_get_and_update_providers_config(self):
        # We can test with the hobbit project
        slug = "the_hobbit_chapter_1"
        res = self.client.get(f"/api/project/{slug}/config/providers")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("llm", data)
        self.assertIn("image", data)
        self.assertIn("backend", data["llm"])
        self.assertIn("backend", data["image"])

        # Test updating providers
        update_payload = {
            "llm": {
                "backend": "openai_compatible",
                "api_base": "https://api.openai.com/v1",
                "api_key": "sk-new-key",
                "context_window": 16384
            },
            "image": {
                "backend": "openai_compatible",
                "openai_api_base": "https://api.openai.com/v1",
                "api_key": "sk-image-new-key",
                "model": "dall-e-3"
            }
        }
        res_post = self.client.post(f"/api/project/{slug}/config/providers", json=update_payload)
        self.assertEqual(res_post.status_code, 200)
        self.assertTrue(res_post.get_json().get("success"))

        # Re-fetch and verify
        res_after = self.client.get(f"/api/project/{slug}/config/providers")
        data_after = res_after.get_json()
        self.assertEqual(data_after["llm"]["backend"], "openai_compatible")
        self.assertEqual(data_after["llm"]["api_base"], "https://api.openai.com/v1")
        self.assertEqual(data_after["llm"]["context_window"], 16384)
        self.assertEqual(data_after["image"]["backend"], "openai_compatible")
        self.assertEqual(data_after["image"]["model"], "dall-e-3")

        # Reset back to local defaults for test project
        reset_payload = {
            "llm": {
                "backend": "lm_studio",
                "api_base": "http://localhost:1234/v1",
                "api_key": "",
                "context_window": 8192
            },
            "image": {
                "backend": "comfyui",
                "comfyui_host": "127.0.0.1:8188",
                "openai_api_base": "https://api.openai.com/v1",
                "api_key": "",
                "model": "dall-e-3"
            }
        }
        self.client.post(f"/api/project/{slug}/config/providers", json=reset_payload)


if __name__ == "__main__":
    unittest.main()
