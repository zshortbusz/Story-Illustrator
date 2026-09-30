"""
tests/test_cover_and_export.py: Comprehensive test suite for Amazon KDP export,
resolution tier system, typography compositing, and Cover Studio.
"""

import os
import json
import shutil
import tempfile
import zipfile
import unittest
from PIL import Image

from pipeline.project_manager import (
    DEFAULT_DIFFUSION_PROFILES,
    get_dimensions_for_tier
)
from pipeline.book_exporter import (
    process_image_for_epub,
    resolve_cover_image,
    export_kdp_bundle,
    export_fxl_epub,
    export_reflowable_epub
)
from pipeline.cover_manager import (
    composite_cover_typography,
    set_existing_scene_as_cover
)


class TestCoverAndKdpExport(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.images_dir = os.path.join(self.temp_dir, "images")
        self.artifacts_dir = os.path.join(self.temp_dir, "artifacts")
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.artifacts_dir, exist_ok=True)

        # Create a sample master scene image (1344x768 PNG)
        self.sample_png = os.path.join(self.images_dir, "scene_001.png")
        img = Image.new("RGB", (1344, 768), color=(40, 60, 90))
        img.save(self.sample_png, format="PNG")

        # Create mock manifest
        self.manifest = {
            "story_title": "The Starlight Chronicles",
            "active_profile": "krea2",
            "resolution_tier": "highres",
            "metadata": {
                "title": "The Starlight Chronicles",
                "author": "Captain Eleanor Vance",
                "publisher": "Aether Books",
                "description": "An epic odyssey across the Orion Cygnus arm."
            },
            "blocks": [
                {
                    "chunk_id": "chunk_001",
                    "text": "The engines roared as the starship leaped into warp.",
                    "action_beat": "Starship jumps into hyperspace",
                    "illustration": {
                        "status": "completed",
                        "image_file": "images/scene_001.png",
                        "prompt": "Sleek starship accelerating into hyperspace warp tunnel",
                        "width": 2048,
                        "height": 1152
                    }
                }
            ]
        }
        with open(os.path.join(self.artifacts_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(self.manifest, f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolution_tier_retrieval(self):
        """Verify standard vs highres dimensions for krea2, zit, sdxl_base, and flux_natural."""
        profiles = DEFAULT_DIFFUSION_PROFILES.get("profiles", {})

        # KREA2
        krea_prof = profiles["krea2"]
        std_land = get_dimensions_for_tier(krea_prof, "landscape", "standard")
        hi_land = get_dimensions_for_tier(krea_prof, "landscape", "highres")
        self.assertEqual(std_land, {"width": 1344, "height": 768})
        self.assertEqual(hi_land, {"width": 2048, "height": 1152})

        std_port = get_dimensions_for_tier(krea_prof, "portrait", "standard")
        hi_port = get_dimensions_for_tier(krea_prof, "portrait", "highres")
        self.assertEqual(std_port, {"width": 896, "height": 1152})  # Book-native 3:4
        self.assertEqual(hi_port, {"width": 1536, "height": 2048})  # Book-native 3:4

        std_cov = get_dimensions_for_tier(krea_prof, "cover", "standard")
        hi_cov = get_dimensions_for_tier(krea_prof, "cover", "highres")
        self.assertEqual(std_cov, {"width": 832, "height": 1344})   # 1:1.6
        self.assertEqual(hi_cov, {"width": 1600, "height": 2560})   # Amazon KDP Gold Standard

        # ZIT
        zit_prof = profiles["zit"]
        zit_hi_land = get_dimensions_for_tier(zit_prof, "landscape", "highres")
        self.assertEqual(zit_hi_land, {"width": 2048, "height": 1152})

        # SDXL
        sdxl_prof = profiles["sdxl_base"]
        sdxl_hi_cov = get_dimensions_for_tier(sdxl_prof, "cover", "highres")
        self.assertEqual(sdxl_hi_cov, {"width": 1600, "height": 2560})

    def test_process_image_for_epub(self):
        """Verify PNG to progressive sRGB JPEG transcoding, sizing, and file size reduction on real artwork."""
        # 1. Test using an actual project master PNG if available
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        real_png = os.path.join(base_dir, "projects", "ash_wednesday", "images", "workflow_api__copperplate_etching", "chunk_004.png")

        test_png = real_png if os.path.isfile(real_png) else self.sample_png
        orig_size = os.path.getsize(test_png)

        jpeg_bytes, mime = process_image_for_epub(test_png, quality=90, max_dim=2400)
        self.assertEqual(mime, "image/jpeg")

        if os.path.isfile(real_png):
            # 2.3MB master PNG should compress down to under 50% in progressive JPEG quality 90
            self.assertLess(len(jpeg_bytes), orig_size * 0.5)

        out_jpg = os.path.join(self.temp_dir, "processed.jpg")
        with open(out_jpg, "wb") as f:
            f.write(jpeg_bytes)

        # Inspect resulting image properties
        with Image.open(out_jpg) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertEqual(im.mode, "RGB")
            self.assertLessEqual(max(im.size), 2400)

    def test_composite_cover_typography(self):
        """Verify typography compositing produces a crisp 1600x2560 sRGB JPEG."""
        marketing_cover = os.path.join(self.temp_dir, "cover_kdp_marketing.jpg")
        epub_cover = os.path.join(self.temp_dir, "cover.jpg")

        composite_cover_typography(
            source_image_path=self.sample_png,
            title="The Starlight Chronicles",
            author="Captain Eleanor Vance",
            output_marketing_path=marketing_cover,
            output_epub_cover_path=epub_cover,
            subtitle="The Lost Sector",
            font_family="serif",
            font_color="gold"
        )

        self.assertTrue(os.path.isfile(marketing_cover))
        self.assertTrue(os.path.isfile(epub_cover))

        with Image.open(marketing_cover) as m_im:
            self.assertEqual(m_im.size, (1600, 2560))
            self.assertEqual(m_im.format, "JPEG")
            self.assertEqual(m_im.mode, "RGB")

        with Image.open(epub_cover) as e_im:
            self.assertEqual(e_im.size, (1600, 2560))
            self.assertEqual(e_im.format, "JPEG")

    def test_set_existing_scene_as_cover(self):
        """Verify using an existing illustrated block creates both covers and updates manifest."""
        cover_record = set_existing_scene_as_cover(
            manifest=self.manifest,
            project_dir=self.temp_dir,
            chunk_id="chunk_001",
            apply_typography=True,
            font_family="sans",
            font_color="white"
        )

        self.assertIsNotNone(cover_record)
        self.assertEqual(cover_record["mode"], "existing")
        self.assertEqual(cover_record["chunk_id"], "chunk_001")
        self.assertEqual(self.manifest["cover"]["mode"], "existing")

        # Verify cover files exist
        expected_mkt = os.path.join(self.temp_dir, "images", "cover", "cover_kdp_marketing.jpg")
        expected_epub = os.path.join(self.temp_dir, "images", "cover", "cover.jpg")
        self.assertTrue(os.path.isfile(expected_mkt))
        self.assertTrue(os.path.isfile(expected_epub))

        with Image.open(expected_mkt) as im:
            self.assertEqual(im.size, (1600, 2560))

    def test_export_kdp_bundle(self):
        """Verify export_kdp_bundle creates a .zip containing EPUB, standalone cover, and metadata sheet."""
        # First ensure a cover is set
        set_existing_scene_as_cover(
            manifest=self.manifest,
            project_dir=self.temp_dir,
            chunk_id="chunk_001",
            apply_typography=True
        )

        zip_out = os.path.join(self.temp_dir, "starlight_kdp_bundle.zip")
        export_kdp_bundle(self.manifest, self.temp_dir, zip_out)

        self.assertTrue(os.path.isfile(zip_out))
        self.assertGreater(os.path.getsize(zip_out), 5000)

        with zipfile.ZipFile(zip_out, "r") as zf:
            names = zf.namelist()
            # Must include 1600x2560 marketing cover
            self.assertIn("cover_kdp_marketing.jpg", names)
            # Must include KDP metadata sheet
            self.assertIn("kdp_metadata_sheet.txt", names)
            # Must include EPUB file
            epub_files = [n for n in names if n.endswith(".epub")]
            self.assertEqual(len(epub_files), 1)

            # Check metadata text content
            meta_content = zf.read("kdp_metadata_sheet.txt").decode("utf-8")
            self.assertIn("Book Title: The Starlight Chronicles", meta_content)
            self.assertIn("Author: Captain Eleanor Vance", meta_content)
            self.assertIn("Publisher: Aether Books", meta_content)
            self.assertIn("An epic odyssey across the Orion Cygnus arm.", meta_content)

    def test_backward_compatibility_old_project(self):
        """Verify projects without resolution_tier or cover records load and export cleanly."""
        legacy_manifest = {
            "story_title": "Legacy Tale",
            "blocks": [
                {
                    "chunk_id": "chunk_001",
                    "text": "Old times in the valley.",
                    "action_beat": "Valley overview",
                    "illustration": {
                        "status": "completed",
                        "image_file": "images/scene_001.png"
                    }
                }
            ]
        }
        # Neither 'cover' nor 'resolution_tier' are in legacy_manifest
        self.assertNotIn("cover", legacy_manifest)
        self.assertNotIn("resolution_tier", legacy_manifest)

        # resolve_cover_image returns None when no dedicated cover exists yet
        cover_info = resolve_cover_image(legacy_manifest, self.temp_dir)
        self.assertIsNone(cover_info)

        # EPUB export should succeed without raising errors, using first illustration as fallback cover
        legacy_epub = os.path.join(self.temp_dir, "legacy.epub")
        export_reflowable_epub(legacy_manifest, self.temp_dir, legacy_epub)
        self.assertTrue(os.path.isfile(legacy_epub))

        # KDP bundle export should succeed, generating standalone cover via fallback
        legacy_bundle = os.path.join(self.temp_dir, "legacy_kdp.zip")
        export_kdp_bundle(legacy_manifest, self.temp_dir, legacy_bundle)
        self.assertTrue(os.path.isfile(legacy_bundle))

        with zipfile.ZipFile(legacy_bundle, "r") as zf:
            self.assertIn("cover_kdp_marketing.jpg", zf.namelist())

    def test_set_existing_scene_with_multi_style(self):
        """Verify selecting a scene from a specific style selects that style's illustration and stores workflow."""
        charcoal_dir = os.path.join(self.images_dir, "ZIT__charcoal_noir")
        os.makedirs(charcoal_dir, exist_ok=True)
        charcoal_png = os.path.join(charcoal_dir, "chunk_001.png")
        Image.new("RGB", (1024, 1024), color=(20, 20, 20)).save(charcoal_png, format="PNG")

        self.manifest["blocks"][0]["illustrations"] = {
            "sdxl_base.json": {
                "status": "completed",
                "image_file": "images/scene_001.png",
                "prompt": "SDXL prompt"
            },
            "ZIT.json (Charcoal & Carbon Noir)": {
                "status": "completed",
                "image_file": "images/ZIT__charcoal_noir/chunk_001.png",
                "prompt": "Dark charcoal sketch",
                "style_name": "Charcoal & Carbon Noir",
                "style_slug": "charcoal_noir"
            }
        }
        with open(os.path.join(self.artifacts_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(self.manifest, f)

        cover_record = set_existing_scene_as_cover(
            manifest=self.manifest,
            project_dir=self.temp_dir,
            chunk_id="chunk_001",
            workflow="ZIT.json (Charcoal & Carbon Noir)"
        )

        self.assertEqual(cover_record["workflow"], "ZIT.json (Charcoal & Carbon Noir)")
        self.assertEqual(self.manifest["cover"]["workflow"], "ZIT.json (Charcoal & Carbon Noir)")
        self.assertEqual(cover_record["prompt"], "Dark charcoal sketch")

    def test_cover_api_endpoint_style_filtering(self):
        """Verify /api/project/<slug>/cover returns available_styles and filters scenes by workflow hermetically."""
        from unittest.mock import patch
        from pipeline.web_server import create_app

        # Set up a multi-style manifest in self.temp_dir
        multi_manifest = dict(self.manifest)
        wf_name = "workflow_api.json (Pre-Raphaelite Impasto & Glaze Oil)"
        wf_folder = "workflow_api__pre_raphaelite_oil"
        wf_img_dir = os.path.join(self.images_dir, wf_folder)
        os.makedirs(wf_img_dir, exist_ok=True)
        img_file = os.path.join(wf_img_dir, "chunk_001.png")
        shutil.copy(self.sample_png, img_file)

        multi_manifest["blocks"][0]["illustrations"] = {
            wf_name: {
                "status": "completed",
                "image_file": f"images/{wf_folder}/chunk_001.png",
                "prompt": "Pre-Raphaelite styled starship",
                "width": 2048,
                "height": 1152
            }
        }
        with open(os.path.join(self.artifacts_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(multi_manifest, f)

        app = create_app()
        client = app.test_client()

        with patch("pipeline.web_server.get_project_dir", return_value=self.temp_dir):
            res = client.get("/api/project/mock_project/cover")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("available_styles", data)
            self.assertIn("available_scenes", data)
            self.assertGreater(len(data["available_styles"]), 0)

            # Verify scenes have human-readable action_beat or title, avoiding 'undefined'
            for s in data["available_scenes"][:3]:
                self.assertIn("chunk_id", s)
                self.assertIn("action_beat", s)
                self.assertNotEqual(s["action_beat"], "undefined")
                self.assertIn("image_url", s)

            # Test filtering by specific style
            import urllib.parse
            res_style = client.get(f"/api/project/mock_project/cover?workflow={urllib.parse.quote(wf_name)}")
            self.assertEqual(res_style.status_code, 200)
            data_style = res_style.get_json()
            self.assertEqual(data_style["active_workflow"], wf_name)
            self.assertIn(wf_folder, data_style["available_scenes"][0]["image_url"])


if __name__ == "__main__":
    unittest.main()
