"""
tests/test_prompt_context_audit.py: Unit and integration tests for the Prompt Context & Visual Bible Audit feature.
"""

import unittest
import json
import os
import shutil
import tempfile

from pipeline.build_manifest import (
    resolve_character_audit_for_scene,
    compose_prompt_context_for_beat,
    run_stage_manifest
)
from pipeline.web_server import create_app


class TestPromptContextAudit(unittest.TestCase):

    def setUp(self):
        self.char_data = {
            "base_dna": "Athletic woman with dark braided hair and sharp grey eyes.",
            "default_attire": "Mechanic denim jumpsuit",
            "timeline_modifications": [
                {
                    "introduced_chunk_id": "chunk_004",
                    "trait": "Jagged scar across right cheekbone from shrapnel"
                }
            ],
            "wardrobe_timeline": [
                {
                    "from_chunk_id": "chunk_000",
                    "context": "Workshop",
                    "attire": "Stained denim overalls and brass goggles"
                },
                {
                    "from_chunk_id": "chunk_003",
                    "context": "Gala Infiltration",
                    "attire": "Dark silk evening gown"
                }
            ]
        }

    def test_character_audit_early_chunk(self):
        """Scene in chunk_002 is before chunk_004: scar must be in skipped_timeline_mods."""
        audit = resolve_character_audit_for_scene(
            char_entry=self.char_data,
            chunk_id="chunk_002",
            beat_attire_override=""
        )

        self.assertIn("Athletic woman", audit["base_dna"])
        self.assertEqual(len(audit["active_timeline_mods"]), 0)
        self.assertEqual(len(audit["skipped_timeline_mods"]), 1)
        self.assertIn("Jagged scar", audit["skipped_timeline_mods"][0]["trait"])
        self.assertIn("Stained denim overalls", audit["resolved_attire"])
        self.assertIn(audit["attire_source"], ["timeline", "wardrobe_timeline"])
        self.assertNotIn("Jagged scar", audit["full_description"])

    def test_character_audit_later_chunk(self):
        """Scene in chunk_005 is after chunk_004: scar must be in active_timeline_mods."""
        audit = resolve_character_audit_for_scene(
            char_entry=self.char_data,
            chunk_id="chunk_005",
            beat_attire_override="Tactical stealth suit"
        )

        self.assertEqual(len(audit["active_timeline_mods"]), 1)
        self.assertIn("Jagged scar", audit["active_timeline_mods"][0]["trait"])
        self.assertEqual(len(audit["skipped_timeline_mods"]), 0)
        self.assertIn(audit["attire_source"], ["beat_override", "scene_override"])
        self.assertIn("Jagged scar", audit["full_description"])
        self.assertIn("Tactical stealth suit", audit["full_description"])

    def test_compose_prompt_context_for_beat(self):
        """Verify compose_prompt_context_for_beat constructs complete payload with all sections."""
        beat = {
            "chunk_id": "chunk_002",
            "scene_type": "landscape",
            "characters_present": ["Lyra"],
            "character_attire": {"Lyra": "Emerald silk cloak"},
            "setting": "Sunken Observatory",
            "action_beat": "Lyra peers through the tarnished bronze telescope.",
            "camera_framing": "Close-up profile shot with soft rim lighting."
        }
        bible = {
            "characters": {"Lyra": self.char_data},
            "settings": {
                "Sunken Observatory": {
                    "visual_keywords": "domed glass, submerged gears, bioluminescent water",
                    "lighting_ambience": "deep blue ethereal twilight",
                    "era_architecture": "ancient brass Victorian astrolabe dome",
                    "full_description": "An underwater glass observatory."
                }
            },
            "global_art_style": "Steampunk Cyberpunk Noir"
        }
        chunks = [{"chunk_id": "chunk_002", "text": "Under the sea, Lyra observed the stars."}]
        profile = {
            "name": "SDXL Base",
            "aspect_ratios": {"landscape": {"width": 1344, "height": 768}},
            "default_negative": "blurry, bad hands"
        }

        ctx = compose_prompt_context_for_beat(
            beat=beat,
            bible=bible,
            chunks=chunks,
            profile=profile,
            active_profile_name="sdxl_base",
            llm_config={"roles": {"PromptSynthesizer": {"model": "test-synth", "temperature": 0.3}}}
        )

        self.assertEqual(ctx["chunk_id"], "chunk_002")
        self.assertEqual(ctx["scene_type"], "landscape")
        self.assertEqual(ctx["dimensions"]["width"], 1344)
        self.assertEqual(ctx["dimensions"]["height"], 768)
        self.assertEqual(ctx["setting"]["name"], "Sunken Observatory")
        self.assertEqual(len(ctx["characters"]), 1)
        self.assertEqual(ctx["characters"][0]["resolved_attire"], "Emerald silk cloak")
        self.assertEqual(ctx["characters"][0]["attire_source"], "beat_override")
        self.assertEqual(len(ctx["characters"][0]["skipped_timeline_mods"]), 1)
        self.assertIn("raw_user_prompt", ctx)
        self.assertIn("system_prompt", ctx)
        self.assertIn("Lyra peers through the tarnished bronze telescope", ctx["raw_user_prompt"])


class TestPromptContextPreviewAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.config["TESTING"] = True
        cls.client = app.test_client()

    def test_preview_endpoint_the_clockwork_duel_chunk_002(self):
        """Test GET /api/project/the_clockwork_duel/prompt_context_preview for chunk_002."""
        res = self.client.get("/api/project/the_clockwork_duel/prompt_context_preview?chunk_id=chunk_002")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        ctx = data.get("preview")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["chunk_id"], "chunk_002")
        elena = next((c for c in ctx["characters"] if c["name"] == "Elena"), None)
        self.assertIsNotNone(elena)
        self.assertEqual(len(elena["active_timeline_mods"]), 0)
        self.assertEqual(len(elena["skipped_timeline_mods"]), 1)
        self.assertIn("scar", elena["skipped_timeline_mods"][0]["trait"].lower())
        self.assertIn("gala gown", elena["resolved_attire"].lower())

    def test_preview_endpoint_the_clockwork_duel_chunk_005(self):
        """Test GET /api/project/the_clockwork_duel/prompt_context_preview for chunk_005."""
        res = self.client.get("/api/project/the_clockwork_duel/prompt_context_preview?chunk_id=chunk_005")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        ctx = data.get("preview")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["chunk_id"], "chunk_005")
        elena = next((c for c in ctx["characters"] if c["name"] == "Elena"), None)
        self.assertIsNotNone(elena)
        self.assertEqual(len(elena["active_timeline_mods"]), 1)
        self.assertIn("scar", elena["active_timeline_mods"][0]["trait"].lower())
        self.assertEqual(len(elena["skipped_timeline_mods"]), 0)
        self.assertIn("combat armor", elena["resolved_attire"].lower())

    def test_preview_endpoint_post_override(self):
        """Test POST /api/project/the_clockwork_duel/prompt_context_preview with live edited beat."""
        payload = {
            "chunk_id": "chunk_002",
            "beat": {
                "chunk_id": "chunk_002",
                "scene_type": "portrait",
                "characters_present": ["Elena"],
                "character_attire": {"Elena": "Crimson leather dueling tunic"},
                "setting": "Sunstone Ballroom",
                "action_beat": "Elena draws her rapier in a dramatic salute.",
                "camera_framing": "Low angle dramatic heroic portrait."
            }
        }
        res = self.client.post("/api/project/the_clockwork_duel/prompt_context_preview", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("success"))
        ctx = data.get("preview")
        self.assertEqual(ctx["scene_type"], "portrait")
        self.assertEqual(ctx["action_beat"], "Elena draws her rapier in a dramatic salute.")
        elena = ctx["characters"][0]
        self.assertEqual(elena["resolved_attire"], "Crimson leather dueling tunic")
        self.assertIn(elena["attire_source"], ["beat_override", "scene_override"])


if __name__ == "__main__":
    unittest.main()

