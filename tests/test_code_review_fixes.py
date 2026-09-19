import os
import json
import unittest
from pipeline.web_server import create_app
from pipeline.chunker import chunk_text
from pipeline.comfy_client import _get_ws_event_loop

class TestCodeReviewFixes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def test_fix_1_debug_mode_disabled_by_default(self):
        """Fix #1: Verify web_server.py does not enable debug mode on 0.0.0.0."""
        server_path = os.path.join(os.path.dirname(__file__), "..", "pipeline", "web_server.py")
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn('app.run(host="0.0.0.0", port=5000, debug=True)', content)
        self.assertIn('debug=False', content)

    def test_fix_2_path_traversal_prevention(self):
        """Fix #2: Verify path traversal in slug parameter is blocked."""
        resp = self.client.get("/api/project/..%2F..%2Fwindows/source")
        self.assertIn(resp.status_code, [400, 404])

        resp_bs = self.client.get("/api/project/..%5C..%5Cwindows/source")
        self.assertIn(resp_bs.status_code, [400, 404])

    def test_fix_9_html_escaping(self):
        """Fix #9: Verify build_site.cjs escapes quotes in escapeHtml."""
        build_path = os.path.join(os.path.dirname(__file__), "..", "build_site.cjs")
        with open(build_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("&quot;", content)
        self.assertIn("&#39;", content)

    def test_fix_11_chunker_dialogue_quotes(self):
        """Fix #11: Verify chunker sentence splitting does not detach dialogue quotes."""
        long_text = ('"Stop right there!" shouted the guard. ' * 50) + '"Never!" said the thief.'
        res = chunk_text(long_text, max_chunk_words=50)
        chunks = res["chunks"]
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            text = c["text"]
            self.assertFalse(text.startswith("shouted the guard."), f"Unexpected split: {text[:40]}")

    def test_fix_8_persistent_event_loop(self):
        """Fix #8: Verify persistent WebSocket event loop is running and reusable."""
        loop1 = _get_ws_event_loop()
        loop2 = _get_ws_event_loop()
        self.assertIs(loop1, loop2)
        self.assertTrue(loop1.is_running())

    def test_fix_3_background_job_execution(self):
        """Fix #3: Verify background stage execution returns job_id and updates status."""
        resp = self.client.post(
            "/api/project/the_raven/run_stage",
            json={"stage": "chunk", "background": True}
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("job_id", data)
        job_id = data["job_id"]

        # Poll job status
        job_resp = self.client.get(f"/api/project/the_raven/job/{job_id}")
        self.assertEqual(job_resp.status_code, 200)
        job_data = job_resp.get_json()
        self.assertEqual(job_data["job_id"], job_id)
        self.assertIn(job_data["status"], ["running", "completed"])

    def test_fix_6_directory_caching(self):
        """Fix #6: Verify project listing uses cached image counts without errors."""
        resp1 = self.client.get("/api/projects")
        self.assertEqual(resp1.status_code, 200)
        projects1 = resp1.get_json()

        # Immediate second call should serve from cache
        resp2 = self.client.get("/api/projects")
        self.assertEqual(resp2.status_code, 200)
        projects2 = resp2.get_json()
        self.assertEqual(projects1, projects2)

if __name__ == "__main__":
    unittest.main()
