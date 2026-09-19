"""
tests/test_timeline_continuity.py: Comprehensive test suite for timeline-aware
character profiles, chronological physical modifications, stateful wardrobe tracking,
and multi-batch dedup (Fix #5).
"""

import unittest
import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock

from pipeline.llm_client import (
    CharacterProfile,
    normalize_character_entry,
    parse_bible_response,
    parse_beats_response
)
from pipeline.build_manifest import (
    chunk_num,
    merge_character_profile,
    merge_setting_profile,
    resolve_character_for_scene,
    match_bible_entity,
    run_stage_manifest
)


class TestTimelineContinuity(unittest.TestCase):

    def test_chunk_num_extraction(self):
        self.assertEqual(chunk_num("chunk_000"), 0)
        self.assertEqual(chunk_num("chunk_025"), 25)
        self.assertEqual(chunk_num("chunk_1042"), 1042)
        self.assertEqual(chunk_num("25"), 25)
        self.assertEqual(chunk_num(25), 25)
        self.assertEqual(chunk_num("none"), 0)

    def test_character_profile_dict_and_string_compatibility(self):
        profile = CharacterProfile({
            "base_dna": "Woman in early 30s, dark braids, grey eyes",
            "default_attire": "Leather aviator jacket, utility trousers",
            "timeline_modifications": [{"introduced_chunk_id": "chunk_025", "trait": "jagged facial scar"}],
            "wardrobe_timeline": [{"from_chunk_id": "chunk_000", "context": "Standard", "attire": "Leather aviator jacket"}]
        })

        # Test dictionary access & serialization
        self.assertEqual(profile["base_dna"], "Woman in early 30s, dark braids, grey eyes")
        self.assertEqual(len(profile["timeline_modifications"]), 1)
        serialized = json.dumps(profile)
        self.assertIn("base_dna", serialized)
        self.assertIn("jagged facial scar", serialized)

        # Test __contains__ backward compatibility
        self.assertIn("dark braids", profile)
        self.assertIn("jagged facial scar", profile)
        self.assertIn("aviator jacket", profile)
        self.assertNotIn("neon pink mohawk", profile)

        # Test string representation
        as_str = str(profile)
        self.assertIn("Woman in early 30s", as_str)
        self.assertIn("Attire: Leather aviator jacket", as_str)

    def test_normalize_character_entry_legacy_string(self):
        legacy = "Valeria: towering warrior with braided silver hair, scarred armor"
        norm = normalize_character_entry(legacy)
        self.assertIsInstance(norm, CharacterProfile)
        self.assertEqual(norm["base_dna"], "Valeria: towering warrior with braided silver hair, scarred armor")
        self.assertEqual(norm["timeline_modifications"], [])

    def test_normalize_character_entry_tagged_subfields(self):
        tagged_text = """Physical DNA: Tall athletic mechanic, messy raven hair, copper goggles
Default Attire: Grease-stained leather duster, combat boots
Physical Change [chunk_025]: Prominent jagged cheek scar
Costume Change [chunk_008] (Grand Ballroom): Emerald velvet evening gown with silver pins
"""
        norm = normalize_character_entry(tagged_text)
        self.assertEqual(norm["base_dna"], "Tall athletic mechanic, messy raven hair, copper goggles")
        self.assertEqual(norm["default_attire"], "Grease-stained leather duster, combat boots")
        self.assertEqual(len(norm["timeline_modifications"]), 1)
        self.assertEqual(norm["timeline_modifications"][0]["introduced_chunk_id"], "chunk_025")
        self.assertEqual(norm["timeline_modifications"][0]["trait"], "Prominent jagged cheek scar")
        self.assertEqual(len(norm["wardrobe_timeline"]), 1)
        self.assertEqual(norm["wardrobe_timeline"][0]["from_chunk_id"], "chunk_008")
        self.assertEqual(norm["wardrobe_timeline"][0]["context"], "Grand Ballroom")

    def test_chronological_scar_appearance(self):
        char = {
            "base_dna": "Elena, woman in early 30s, sharp angular jawline, dark braided raven hair, grey eyes",
            "timeline_modifications": [
                {
                    "introduced_chunk_id": "chunk_025",
                    "trait": "prominent jagged diagonal scar across left cheek"
                },
                {
                    "introduced_chunk_id": "chunk_040",
                    "trait": "brass cybernetic right forearm prosthetic"
                }
            ],
            "default_attire": "Weathered leather aviator jacket, cargo trousers"
        }

        # Early in story (chunk_005): NO scar, NO prosthetic
        desc_005 = resolve_character_for_scene(char, "chunk_005")
        self.assertNotIn("scar", desc_005.lower())
        self.assertNotIn("cybernetic", desc_005.lower())
        self.assertIn("dark braided raven hair", desc_005)

        # Right before duel (chunk_024): still NO scar
        desc_024 = resolve_character_for_scene(char, "chunk_024")
        self.assertNotIn("scar", desc_024.lower())

        # At duel chunk (chunk_025): Scar becomes ACTIVE
        desc_025 = resolve_character_for_scene(char, "chunk_025")
        self.assertIn("jagged diagonal scar", desc_025.lower())
        self.assertNotIn("cybernetic", desc_025.lower())

        # After duel (chunk_030): Scar remains ACTIVE, no prosthetic yet
        desc_030 = resolve_character_for_scene(char, "chunk_030")
        self.assertIn("jagged diagonal scar", desc_030.lower())
        self.assertNotIn("cybernetic", desc_030.lower())

        # Chapter 6 (chunk_045): BOTH scar and cybernetic arm are active
        desc_045 = resolve_character_for_scene(char, "chunk_045")
        self.assertIn("jagged diagonal scar", desc_045.lower())
        self.assertIn("brass cybernetic right forearm", desc_045.lower())

    def test_wardrobe_timeline_continuity_and_inheritance(self):
        char = {
            "base_dna": "Elena, woman in early 30s, dark braids",
            "wardrobe_timeline": [
                {
                    "from_chunk_id": "chunk_000",
                    "context": "Workshop",
                    "attire": "Brown leather flight jacket, utility cargo trousers"
                },
                {
                    "from_chunk_id": "chunk_008",
                    "context": "Grand Ballroom",
                    "attire": "Floor-length emerald velvet evening gown with silver combs"
                },
                {
                    "from_chunk_id": "chunk_015",
                    "context": "Night Escape",
                    "attire": "Dark hooded traveler's cloak, leather riding boots"
                }
            ],
            "default_attire": "Brown leather flight jacket, utility cargo trousers"
        }

        # Scene at chunk_003: Workshop flight jacket
        desc_003 = resolve_character_for_scene(char, "chunk_003")
        self.assertIn("flight jacket", desc_003.lower())
        self.assertNotIn("emerald", desc_003.lower())

        # Scene at chunk_008: Changes to emerald velvet gown
        desc_008 = resolve_character_for_scene(char, "chunk_008")
        self.assertIn("emerald velvet evening gown", desc_008.lower())
        self.assertNotIn("flight jacket", desc_008.lower())

        # Scene at chunk_010 (dancing waltz, no clothing words in text): Inherits gown!
        desc_010 = resolve_character_for_scene(char, "chunk_010")
        self.assertIn("emerald velvet evening gown", desc_010.lower())
        self.assertNotIn("flight jacket", desc_010.lower())

        # Scene at chunk_016: Escape cloak
        desc_016 = resolve_character_for_scene(char, "chunk_016")
        self.assertIn("dark hooded traveler's cloak", desc_016.lower())
        self.assertNotIn("emerald", desc_016.lower())

    def test_beat_attire_override_precedence(self):
        char = {
            "base_dna": "Elena, woman in early 30s, dark braids",
            "wardrobe_timeline": [
                {
                    "from_chunk_id": "chunk_008",
                    "context": "Grand Ballroom",
                    "attire": "Emerald velvet evening gown"
                }
            ]
        }

        # Manual beat override specifies torn hem
        desc = resolve_character_for_scene(
            char,
            chunk_id="chunk_011",
            beat_attire_override="torn hem emerald gown, bare feet"
        )
        self.assertIn("torn hem emerald gown, bare feet", desc)

    def test_merge_character_profile_growth_prevention_fix5(self):
        # Initial batch
        initial_profile = CharacterProfile({
            "base_dna": "Tall slender mechanic with copper-tinted goggles, grease-stained leather duster, cybernetic arm",
            "default_attire": "Grease-stained leather duster, heavy boots"
        })

        accumulated = initial_profile
        initial_len = len(accumulated["base_dna"])

        # 5 subsequent batches repeating the character with slight word variations
        variations = [
            "Lean young technician, brass goggles pushed up, dark coat, mechanical arm",
            "Slender mechanic with soot on his cheek, round goggles, worn brown duster, metallic limb",
            "Disheveled engineer with copper goggles, leather coat, mechanical prosthetic",
            "Sentry with goggles and cybernetic arm, dark jacket",
            "Mechanic in duster with brass arm"
        ]

        for i, var_text in enumerate(variations, 2):
            cid = f"chunk_{i*5:03d}"
            accumulated = merge_character_profile(accumulated, var_text, current_chunk_id=cid)

        # Verify base_dna did NOT balloon uncontrollably across the 5 batches
        self.assertLessEqual(len(accumulated["base_dna"]), initial_len + 50)

    def test_merge_character_profile_ingests_modifications_and_costumes(self):
        initial = CharacterProfile({
            "base_dna": "Elena, 30yo woman with dark hair",
            "default_attire": "Work overalls"
        })

        # Batch 2 introduces a costume change
        batch2_update = {
            "base_dna": "Elena, 30yo woman with dark hair",
            "wardrobe_timeline": [
                {"from_chunk_id": "chunk_010", "context": "Gala", "attire": "Silk evening gown"}
            ]
        }
        merged = merge_character_profile(initial, batch2_update, current_chunk_id="chunk_010")
        self.assertEqual(len(merged["wardrobe_timeline"]), 2)
        self.assertEqual(merged["wardrobe_timeline"][-1]["attire"], "Silk evening gown")

        # Batch 4 introduces a scar
        batch4_update = {
            "base_dna": "Elena, 30yo woman with dark hair",
            "timeline_modifications": [
                {"introduced_chunk_id": "chunk_025", "trait": "jagged facial scar across left cheek"}
            ]
        }
        merged2 = merge_character_profile(merged, batch4_update, current_chunk_id="chunk_025")
        self.assertEqual(len(merged2["timeline_modifications"]), 1)
        self.assertEqual(merged2["timeline_modifications"][0]["trait"], "jagged facial scar across left cheek")

    def test_merge_setting_profile_dedup(self):
        existing = "The Rust Catwalks: industrial scaffolding of decaying iron, dense yellow fog"
        repeat = "The Rust Catwalks: iron scaffolding, dense industrial fog, decaying metal"
        merged = merge_setting_profile(existing, repeat)
        # Should detect high overlap and not duplicate
        self.assertEqual(merged, existing)

    def test_parse_beats_with_character_attire(self):
        raw_beats_text = """[BEAT]
Chunk: chunk_012
Scene Type: landscape
Characters: Elena, Lord Vance
Attire: Elena: emerald velvet evening gown; Lord Vance: gilded black doublet
Setting: Grand Ballroom
Action: Elena whispers a warning behind her champagne glass
Camera: Medium close-up, warm candlelight
"""
        beats = parse_beats_response(raw_beats_text, {"chunk_012"})
        self.assertEqual(len(beats), 1)
        beat = beats[0]
        self.assertEqual(beat["chunk_id"], "chunk_012")
        self.assertIn("Elena", beat["characters_present"])
        self.assertIn("Lord Vance", beat["characters_present"])
        self.assertIn("Elena", beat["character_attire"])
        self.assertEqual(beat["character_attire"]["Elena"], "emerald velvet evening gown")
        self.assertEqual(beat["character_attire"]["Lord Vance"], "gilded black doublet")

    def test_end_to_end_manifest_timeline_synthesis(self):
        """Verify run_stage_manifest builds time-accurate prompts for multi-scene story."""
        temp_dir = tempfile.mkdtemp()
        try:
            art_dir = os.path.join(temp_dir, "artifacts")
            cfg_dir = os.path.join(temp_dir, "config")
            os.makedirs(art_dir, exist_ok=True)
            os.makedirs(cfg_dir, exist_ok=True)

            # 01_chunks.json
            with open(os.path.join(art_dir, "01_chunks.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "chunks": [
                        {"chunk_id": "chunk_005", "text": "Elena tightened the valve in the workshop."},
                        {"chunk_id": "chunk_012", "text": "Elena waltzed through the Grand Ballroom."},
                        {"chunk_id": "chunk_030", "text": "Elena stood on the battlefield, her cheek scarred from the duel."}
                    ]
                }, f)

            # 03_visual_bible.json
            with open(os.path.join(art_dir, "03_visual_bible.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "global_art_style": "1980s dark anime aesthetic, muted tones",
                    "characters": {
                        "Elena": {
                            "base_dna": "Elena, 30yo woman with dark braided hair and grey eyes",
                            "timeline_modifications": [
                                {"introduced_chunk_id": "chunk_025", "trait": "jagged facial scar"}
                            ],
                            "wardrobe_timeline": [
                                {"from_chunk_id": "chunk_000", "context": "Workshop", "attire": "leather aviator jacket"},
                                {"from_chunk_id": "chunk_010", "context": "Grand Ballroom", "attire": "emerald velvet gown"}
                            ],
                            "default_attire": "leather aviator jacket"
                        }
                    },
                    "settings": {
                        "Grand Ballroom": "Gilded ballroom with chandeliers"
                    }
                }, f)

            # 02_selected_beats.json
            with open(os.path.join(art_dir, "02_selected_beats.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "selected_beats": [
                        {
                            "chunk_id": "chunk_005",
                            "scene_type": "landscape",
                            "characters_present": ["Elena"],
                            "character_attire": {},
                            "setting": "Workshop",
                            "action_beat": "Elena adjusting valve",
                            "camera_framing": "medium shot"
                        },
                        {
                            "chunk_id": "chunk_012",
                            "scene_type": "landscape",
                            "characters_present": ["Elena"],
                            "character_attire": {},
                            "setting": "Grand Ballroom",
                            "action_beat": "Elena waltzing",
                            "camera_framing": "wide shot"
                        },
                        {
                            "chunk_id": "chunk_030",
                            "scene_type": "landscape",
                            "characters_present": ["Elena"],
                            "character_attire": {"Elena": "tactical combat armor"},
                            "setting": "Battlefield",
                            "action_beat": "Elena standing on battlefield",
                            "camera_framing": "dramatic low angle"
                        }
                    ]
                }, f)

            # diffusion_profiles.json
            with open(os.path.join(cfg_dir, "diffusion_profiles.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "active_profile": "test_profile",
                    "profiles": {
                        "test_profile": {
                            "aspect_ratios": {"landscape": {"width": 1024, "height": 768}},
                            "system_prompt": "Synthesize prompts.",
                            "default_negative": "blurry",
                            "positive_prefix": "masterpiece"
                        }
                    }
                }, f)

            # Mock LLM Client that echoes character traits received in the prompt
            mock_client = MagicMock()
            mock_client.resolve_model.return_value = "mock-model"

            def mock_chat_text(messages, **kwargs):
                user_msg = messages[-1]["content"]
                # Echo whatever Characters Present section contains
                char_snippet = ""
                for line in user_msg.split("\n"):
                    if "Visual Traits:" in line:
                        char_snippet += line + " "
                return f"PROMPT: masterpiece, {char_snippet.strip()}\nNEGATIVE: blurry"

            mock_client.chat_text.side_effect = mock_chat_text

            llm_config = {
                "roles": {
                    "prompt_synthesizer": {
                        "model": "mock-model",
                        "temperature": 0.35,
                        "max_tokens": -1
                    }
                }
            }

            manifest = run_stage_manifest(temp_dir, mock_client, llm_config)
            blocks = manifest.get("blocks", [])
            self.assertEqual(len(blocks), 3)

            # Chunk 005: leather jacket, NO scar
            p_005 = blocks[0]["illustration"]["prompt"]
            self.assertIn("leather aviator jacket", p_005)
            self.assertNotIn("emerald velvet gown", p_005)
            self.assertNotIn("jagged facial scar", p_005)

            # Chunk 012: emerald gown (inherited from chunk 010!), NO scar
            p_012 = blocks[1]["illustration"]["prompt"]
            self.assertIn("emerald velvet gown", p_012)
            self.assertNotIn("leather aviator jacket", p_012)
            self.assertNotIn("jagged facial scar", p_012)

            # Chunk 030: tactical armor AND jagged facial scar ACTIVE
            p_030 = blocks[2]["illustration"]["prompt"]
            self.assertIn("tactical combat armor", p_030)
            self.assertIn("jagged facial scar", p_030)
            self.assertNotIn("emerald velvet gown", p_030)

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
