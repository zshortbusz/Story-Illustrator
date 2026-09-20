"""
tests/test_global_styles.py: Unit tests for cross-project universal style library persistence.
"""

import os
import json
import shutil
import tempfile
import unittest
from pipeline.project_manager import (
    get_global_styles_path,
    load_global_styles,
    save_global_styles,
    merge_into_global_styles,
    slugify_style,
    get_project_styles,
    update_project_active_style,
    init_project
)


class TestGlobalStyles(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "test_story")
        init_project("test_story", base_dir=self.temp_dir, input_text="Sample story content.")
        # Isolate global styles to temp dir
        self.test_global_path = os.path.join(self.temp_dir, "global_styles.json")
        real_global = get_global_styles_path()
        if os.path.isfile(real_global):
            shutil.copyfile(real_global, self.test_global_path)
        os.environ["GLOBAL_STYLES_PATH"] = self.test_global_path

    def tearDown(self):
        os.environ.pop("GLOBAL_STYLES_PATH", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_global_styles(self):
        styles = load_global_styles()
        self.assertIn("art", styles)
        self.assertIn("photography", styles)
        self.assertGreaterEqual(len(styles["art"]), 1)
        self.assertGreaterEqual(len(styles["photography"]), 1)

    def test_merge_into_global_styles_deduplication(self):
        new_styles = [
            {
                "id": "charcoal_test_unique",
                "name": "Unique Charcoal Style",
                "description": "Short desc",
                "category": "art"
            }
        ]
        # First merge
        lib1 = merge_into_global_styles(new_styles, category="art", source_project="test_story")
        item1 = next((s for s in lib1["art"] if s["id"] == "charcoal_test_unique"), None)
        self.assertIsNotNone(item1)
        self.assertEqual(item1["description"], "Short desc")

        # Second merge with longer, richer description should update existing item without adding duplicates
        richer_styles = [
            {
                "id": "charcoal_test_unique",
                "name": "Unique Charcoal Style",
                "description": "Vastly expanded rich description of carbon black tones and cold-press tooth",
                "category": "art"
            }
        ]
        lib2 = merge_into_global_styles(richer_styles, category="art", source_project="test_story")
        matches = [s for s in lib2["art"] if s["id"] == "charcoal_test_unique"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["description"], richer_styles[0]["description"])

    def test_project_styles_and_active_selection(self):
        # Create a mock 03_visual_bible.json
        bible_path = os.path.join(self.project_dir, "artifacts", "03_visual_bible.json")
        os.makedirs(os.path.dirname(bible_path), exist_ok=True)
        with open(bible_path, "w", encoding="utf-8") as f:
            json.dump({
                "global_art_style": "Dark gothic oil painting",
                "characters": {},
                "settings": {},
                "style_presets": {
                    "art": [
                        {"id": "style_1", "name": "Style 1", "description": "Desc 1", "category": "art"}
                    ],
                    "photography": [
                        {"id": "photo_1", "name": "Photo 1", "description": "Desc P1", "category": "photography"}
                    ]
                }
            }, f, indent=2)

        data = get_project_styles(self.project_dir)
        self.assertEqual(len(data["presets"]["art"]), 1)
        self.assertEqual(data["presets"]["art"][0]["name"], "Style 1")
        self.assertEqual(len(data["presets"]["photography"]), 1)

        # Update active style selection
        updated = update_project_active_style(
            project_dir=self.project_dir,
            style_id="photo_1",
            style_name="Photo 1",
            description="Desc P1",
            category="photography"
        )
        self.assertEqual(updated["active_style"]["id"], "photo_1")
        self.assertEqual(updated["global_art_style"], "Desc P1")

        # Reload and verify persistence
        reloaded = get_project_styles(self.project_dir)
        self.assertEqual(reloaded["active_style"]["id"], "photo_1")


if __name__ == "__main__":
    unittest.main()
