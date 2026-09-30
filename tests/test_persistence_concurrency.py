"""
tests/test_persistence_concurrency.py: Tests for atomic file writing,
corrupted config recovery, and persistence safety in project_manager.
"""

import os
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from pipeline.project_manager import (
    save_global_styles,
    load_global_styles,
    update_project_diffusion_profile,
    merge_into_global_styles
)


class TestPersistenceConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_corrupted_diffusion_profiles_list_recovery(self):
        """Verifies update_project_diffusion_profile safely recovers when diffusion_profiles.json is a list."""
        cfg_dir = os.path.join(self.temp_dir, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        diff_path = os.path.join(cfg_dir, "diffusion_profiles.json")

        # Write a JSON list instead of a dict (e.g. corrupted config)
        with open(diff_path, "w", encoding="utf-8") as f:
            json.dump(["corrupted", "config", "list"], f)

        try:
            res = update_project_diffusion_profile(self.temp_dir, "sdxl_base", {"steps": 30})
            self.assertIsInstance(res, dict)
            self.assertIn("sdxl_base", res)
        except TypeError as te:
            self.fail(f"BUG REPRODUCED: update_project_diffusion_profile crashed on non-dict config: {te}")

    def test_save_global_styles_atomic_replace(self):
        """Verifies save_global_styles uses an atomic tempfile-replace mechanism rather than direct open('w')."""
        from unittest.mock import patch
        data = {
            "art": [{"name": "Impasto", "id": "impasto"}],
            "photography": []
        }
        temp_styles_path = os.path.join(self.temp_dir, "config", "global_styles.json")
        with patch("pipeline.project_manager.get_global_styles_path", return_value=temp_styles_path):
            with patch("os.replace") as mock_replace:
                save_global_styles(data)
                self.assertTrue(
                    mock_replace.called,
                    "BUG REPRODUCED: save_global_styles does direct non-atomic write without os.replace temp file!"
                )


if __name__ == "__main__":
    unittest.main()
