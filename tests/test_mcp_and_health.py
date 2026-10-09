"""
tests/test_mcp_and_health.py: Unit tests for health check diagnostics and MCP server tools.
"""

import unittest
import os
import tempfile
import json
from pipeline.health_check import check_python_version, check_dependencies, check_directories, run_all_checks
import pipeline.mcp_server as mcp_srv


class TestHealthCheck(unittest.TestCase):
    def test_python_version_check(self):
        res = check_python_version()
        self.assertTrue(res["passed"])
        self.assertIn("version", res)

    def test_dependencies_check(self):
        res = check_dependencies()
        self.assertTrue(res["passed"])
        self.assertIn("flask", res["installed"])
        self.assertIn("reportlab", res["installed"])
        self.assertEqual(len(res["missing_required"]), 0)

    def test_directories_check(self):
        res = check_directories()
        self.assertTrue(res["passed"])
        self.assertGreater(len(res["workflows_found"]), 0)

    def test_run_all_checks_structure(self):
        res = run_all_checks()
        self.assertIn("status", res)
        self.assertIn("core_ready", res)
        self.assertIn("services", res)
        self.assertIn("environment", res)
        self.assertTrue(res["core_ready"])


class TestMCPServerTools(unittest.TestCase):
    def test_create_mcp_app(self):
        app = mcp_srv.create_mcp_app()
        self.assertIsNotNone(app)

    def test_tool_list_projects(self):
        projects = mcp_srv.tool_list_projects()
        self.assertIsInstance(projects, list)
        self.assertGreater(len(projects), 0)
        first = projects[0]
        self.assertIn("slug", first)
        self.assertIn("title", first)
        self.assertIn("total_scenes", first)

    def test_tool_get_project_status(self):
        projects = mcp_srv.tool_list_projects()
        if projects:
            slug = projects[0]["slug"]
            status = mcp_srv.tool_get_project_status(slug)
            self.assertEqual(status["slug"], slug)
            self.assertIn("pipeline_progress", status)
            self.assertIn("chunks_count", status["pipeline_progress"])

    def test_tool_create_project_and_status(self):
        import pipeline.project_manager as pm
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_pm_base = pm.get_base_dir
            orig_srv_base = mcp_srv.get_base_dir
            try:
                pm.get_base_dir = lambda: tmpdir
                mcp_srv.get_base_dir = lambda: tmpdir
                res = mcp_srv.tool_create_project("Agent Test Story", "This is a test manuscript for AI agents.")
                self.assertTrue(res["success"])
                self.assertEqual(res["slug"], "agent_test_story")

                status = mcp_srv.tool_get_project_status("agent_test_story")
                self.assertEqual(status["slug"], "agent_test_story")
                self.assertTrue(status["pipeline_progress"]["has_raw_story"])
            finally:
                pm.get_base_dir = orig_pm_base
                mcp_srv.get_base_dir = orig_srv_base


if __name__ == "__main__":
    unittest.main()
