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

if __name__ == "__main__":
    unittest.main()
