import os
import shutil
import unittest
import json
from pipeline.web_server import create_app

class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("lm_studio", data)
        self.assertIn("comfyui", data)
        self.assertIn("instructions", data)

    def test_projects_list(self):
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        slugs = [p["slug"] for p in data]
        self.assertIn("the_raven", slugs)

    def test_workflows_list(self):
        resp = self.client.get("/api/workflows")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("workflows", data)
        self.assertIn("sdxl_base.json", data["workflows"])

    def test_get_and_update_llm_config(self):
        slug = "the_raven"
        resp = self.client.get(f"/api/project/{slug}/config/llm")
        self.assertEqual(resp.status_code, 200)
        cfg = resp.get_json()
        self.assertIn("roles", cfg)

        # Update
        cfg["roles"]["narrative_director"]["temperature"] = 0.35
        update_resp = self.client.post(
            f"/api/project/{slug}/config/llm",
            data=json.dumps(cfg),
            content_type="application/json"
        )
        self.assertEqual(update_resp.status_code, 200)

        # Verify
        verify_resp = self.client.get(f"/api/project/{slug}/config/llm")
        self.assertEqual(verify_resp.get_json()["roles"]["narrative_director"]["temperature"], 0.35)

    def test_metadata_and_export_endpoints(self):
        slug = "the_raven"
        # Test GET metadata
        get_resp = self.client.get(f"/api/project/{slug}/metadata")
        self.assertEqual(get_resp.status_code, 200)
        meta_data = get_resp.get_json()
        self.assertTrue(meta_data.get("success"))
        self.assertIn("metadata", meta_data)

        # Test POST metadata
        post_resp = self.client.post(
            f"/api/project/{slug}/metadata",
            data=json.dumps({
                "author": "Edgar Allan Poe",
                "publisher": "Gothic Classic Editions",
                "language": "en",
                "description": "The quintessential Gothic poem."
            }),
            content_type="application/json"
        )
        self.assertEqual(post_resp.status_code, 200)
        updated_meta = post_resp.get_json()["metadata"]
        self.assertEqual(updated_meta["author"], "Edgar Allan Poe")
        self.assertEqual(updated_meta["publisher"], "Gothic Classic Editions")

        # Test Export PDF
        pdf_resp = self.client.get(f"/api/project/{slug}/export/pdf")
        self.assertEqual(pdf_resp.status_code, 200)
        self.assertEqual(pdf_resp.mimetype, "application/pdf")
        self.assertGreater(len(pdf_resp.data), 1000)

        # Test Export FXL EPUB
        fxl_resp = self.client.get(f"/api/project/{slug}/export/fxl_epub")
        self.assertEqual(fxl_resp.status_code, 200)
        self.assertEqual(fxl_resp.mimetype, "application/epub+zip")
        self.assertGreater(len(fxl_resp.data), 1000)

        # Test Export Reflowable EPUB
        reflow_resp = self.client.get(f"/api/project/{slug}/export/reflowable_epub")
        self.assertEqual(reflow_resp.status_code, 200)
        self.assertEqual(reflow_resp.mimetype, "application/epub+zip")
        self.assertGreater(len(reflow_resp.data), 1000)

    def test_compile_reader_endpoint(self):
        """Verifies POST /api/project/<slug>/compile runs without NameError: compile_html."""
        slug = "the_raven"
        resp = self.client.post(
            f"/api/project/{slug}/compile",
            data=json.dumps({"embed_images": False}),
            content_type="application/json"
        )
        self.assertEqual(
            resp.status_code,
            200,
            f"compile_reader_endpoint failed with {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("path", data)
        # Clean up compiled index.html
        if os.path.isfile(data["path"]):
            try:
                os.remove(data["path"])
            except Exception:
                pass

    def test_render_cover_endpoint(self):
        """Verifies POST /api/project/<slug>/cover/render runs without NameError (load_image_config, Image) or AttributeError (generate_image)."""
        from unittest.mock import patch, MagicMock
        from PIL import Image
        import os
        import tempfile
        import shutil
        slug = "the_raven"

        manifest_path = os.path.join(self.app.root_path, "projects", slug, "artifacts", "manifest.json") if hasattr(self.app, "root_path") else ""
        from pipeline.web_server import get_project_dir
        pdir = get_project_dir(slug)
        manifest_file = os.path.join(pdir, "artifacts", "manifest.json")
        orig_manifest = None
        if os.path.isfile(manifest_file):
            with open(manifest_file, "r", encoding="utf-8") as f:
                orig_manifest = f.read()

        # Mock Image Client
        mock_client = MagicMock()
        def mock_render_side_effect(*args, **kwargs):
            out_p = kwargs.get("output_path") or kwargs.get("output_filepath")
            if out_p:
                os.makedirs(os.path.dirname(out_p), exist_ok=True)
                im = Image.new("RGB", (100, 100), color=(20, 20, 40))
                im.save(out_p)
            return {"status": "success", "images": [out_p]}

        mock_client.render.side_effect = mock_render_side_effect
        mock_client.generate_image.side_effect = mock_render_side_effect

        try:
            with patch("pipeline.image_client.create_image_client", return_value=mock_client):
                resp = self.client.post(
                    f"/api/project/{slug}/cover/render",
                    data=json.dumps({
                        "prompt": "Gothic raven perched on bust of Pallas",
                        "negative_prompt": "blurry",
                        "apply_typography": False,
                        "tier": "standard"
                    }),
                    content_type="application/json"
                )
                self.assertEqual(
                    resp.status_code,
                    200,
                    f"render_cover_endpoint failed with {resp.status_code}: {resp.get_data(as_text=True)}"
                )
                data = resp.get_json()
                self.assertTrue(data.get("success"))
                self.assertIn("cover", data)
        finally:
            if orig_manifest is not None and os.path.isfile(manifest_file):
                with open(manifest_file, "w", encoding="utf-8") as f:
                    f.write(orig_manifest)
            cover_dir = os.path.join(pdir, "images", "cover")
            if os.path.isdir(cover_dir):
                shutil.rmtree(cover_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
