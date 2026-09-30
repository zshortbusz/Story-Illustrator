"""
tests/test_frontend_syntax.py: Automated static analysis and syntax validation
for frontend web assets using Node.js syntax parsing.
"""

import os
import shutil
import subprocess
import unittest

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS_PATH = os.path.join(WORKSPACE_DIR, "pipeline", "web_static", "app.js")


class TestFrontendSyntax(unittest.TestCase):
    def test_app_js_syntax_check(self):
        """Validates that pipeline/web_static/app.js has zero JavaScript syntax errors via node -c."""
        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js is not installed; skipping frontend syntax validation.")

        self.assertTrue(os.path.isfile(APP_JS_PATH), f"app.js missing at {APP_JS_PATH}")

        result = subprocess.run(
            [node_bin, "-c", APP_JS_PATH],
            capture_output=True,
            text=True
        )

        self.assertEqual(
            result.returncode,
            0,
            f"JavaScript syntax error detected in app.js:\n{result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
