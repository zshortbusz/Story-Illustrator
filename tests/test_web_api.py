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
        self.assertIn("the_rust_forest", slugs)

    def test_workflows_list(self):
        resp = self.client.get("/api/workflows")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("workflows", data)
        self.assertIn("sdxl_base.json", data["workflows"])

    def test_get_and_update_llm_config(self):
        slug = "the_rust_forest"
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

if __name__ == "__main__":
    unittest.main()
