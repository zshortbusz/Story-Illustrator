import unittest
from pipeline.llm_client import (
    LMStudioClient,
    parse_beats_response,
    parse_bible_response,
    parse_prompt_response
)

class TestLLMClient(unittest.TestCase):
    def setUp(self):
        self.client = LMStudioClient()

    def test_extract_json_block_markdown(self):
        markdown_resp = """Here is the JSON you requested:
```json
{
  "selected_beats": [
    {
      "chunk_id": "chunk_004",
      "action_beat": "Kaelen jumps"
    }
  ]
}
```
Hope this helps!"""
        extracted = self.client._extract_json_block(markdown_resp)
        self.assertTrue(extracted.startswith("{"))
        self.assertTrue(extracted.endswith("}"))
        self.assertIn("selected_beats", extracted)

    def test_clean_json_trailing_commas(self):
        malformed = '{"items": ["a", "b",], "val": 1,}'
        cleaned = self.client._clean_json_syntax(malformed)
        self.assertEqual(cleaned, '{"items": ["a", "b"], "val": 1}')

    def test_check_health_offline_handling(self):
        bad_client = LMStudioClient(api_base="http://localhost:9999/v1")
        health = bad_client.check_health()
        self.assertFalse(health["online"])
        self.assertEqual(health["models"], [])

    def test_parse_beats_from_free_form_text(self):
        free_text = """Based on my literary analysis, here is the visual beat for this section:

[BEAT]
Chunk: chunk_003
Scene Type: landscape
Characters: Kaelen, Lyra
Setting: The Rust Catwalks
Action: Kaelen leaping across a collapsed section of iron catwalk amidst flying sparks
Camera: dynamic low-angle action shot, dramatic edge lighting
"""
        beats = parse_beats_response(free_text, {"chunk_003", "chunk_004"})
        self.assertEqual(len(beats), 1)
        b = beats[0]
        self.assertEqual(b["chunk_id"], "chunk_003")
        self.assertEqual(b["scene_type"], "landscape")
        self.assertEqual(b["characters_present"], ["Kaelen", "Lyra"])
        self.assertEqual(b["setting"], "The Rust Catwalks")
        self.assertIn("leaping across", b["action_beat"])
        self.assertIn("low-angle", b["camera_framing"])

    def test_parse_beats_from_none(self):
        none_text = "NONE - These chunks are purely expository dialog and do not warrant an illustration."
        beats = parse_beats_response(none_text, {"chunk_000", "chunk_001"})
        self.assertEqual(beats, [])

    def test_parse_bible_from_natural_text(self):
        natural_text = """
GLOBAL ART STYLE: 1980s dark anime aesthetic, muted tones, cinematic cel shading

CHARACTER: Kaelen: man late 20s, scarred cheek, brass mechanical left arm, tattered canvas duster coat
SETTING: The Rust Catwalks: towers of decaying iron girders, hanging cables, damp industrial fog
"""
        bible = parse_bible_response(natural_text, ["Kaelen"], ["The Rust Catwalks"])
        self.assertIn("1980s dark anime", bible["global_art_style"])
        self.assertIn("brass mechanical left arm", bible["characters"].get("Kaelen", ""))
        self.assertIn("decaying iron girders", bible["settings"].get("The Rust Catwalks", ""))

    def test_parse_bible_from_orion_bold_markdown(self):
        orion_text = """**GLOBAL ART STYLE:** Industrial Steampunk Decay. Heavy textures of oxidation and rust.

**CHARACTER: Kaelen:** A rugged figure wearing a tattered canvas duster coat; features a prominent brass mechanical arm composed of visible interlocking gears.

**SETTING: The Dead City (Iron Forest):** An endless expanse of oxidized metal cables and decaying girders.
"""
        bible = parse_bible_response(orion_text)
        self.assertIn("Industrial Steampunk Decay", bible["global_art_style"])
        self.assertNotIn("**", bible["global_art_style"])
        self.assertIn("Kaelen", bible["characters"])
        self.assertNotIn("**", bible["characters"]["Kaelen"])
        self.assertIn("brass mechanical arm", bible["characters"]["Kaelen"])
        self.assertIn("The Dead City (Iron Forest)", bible["settings"])
        self.assertNotIn("**", bible["settings"]["The Dead City (Iron Forest)"])

    def test_parse_prompt_from_tagged_and_raw_text(self):
        tagged = """
PROMPT: cinematic shot of a brass mechanical warrior in industrial fog, sharp lighting
NEGATIVE: blurry, extra arms, low quality, oversaturated
"""
        pos, neg = parse_prompt_response(tagged, default_negative="default neg")
        self.assertEqual(pos, "cinematic shot of a brass mechanical warrior in industrial fog, sharp lighting")
        self.assertEqual(neg, "blurry, extra arms, low quality, oversaturated")

        raw = "Here is the diffusion prompt: dynamic wide angle view of an airship soaring through clouds."
        pos2, neg2 = parse_prompt_response(raw, default_negative="blurry, deformed")
        self.assertEqual(pos2, "dynamic wide angle view of an airship soaring through clouds.")
        self.assertEqual(neg2, "blurry, deformed")

    def test_parse_prompt_from_reasoning_and_json_variants(self):
        # Reasoning model preamble followed by PROMPT tag
        reasoning_resp = """Thinking Process:
1. Analyze user request: The user wants a prompt for chunk_000.
2. Character visual traits: Kaelen has a brass arm.
3. Scene: foggy industrial forest.

PROMPT: **A lean man with a brass mechanical arm standing atop rusted girders shrouded in dense fog**, cinematic lighting, 8k
NEGATIVE: blurry, lowres, extra limbs
"""
        pos, neg = parse_prompt_response(reasoning_resp, default_negative="default neg")
        self.assertEqual(pos, "A lean man with a brass mechanical arm standing atop rusted girders shrouded in dense fog, cinematic lighting, 8k")
        self.assertEqual(neg, "blurry, lowres, extra limbs")

        # JSON variant with 'positive_prompt' key
        json_resp = '{"positive_prompt": "cinematic digital painting of a rusted forest", "negative_prompt": "text, watermarks"}'
        pos_j, neg_j = parse_prompt_response(json_resp, default_negative="default neg")
        self.assertEqual(pos_j, "cinematic digital painting of a rusted forest")
        self.assertEqual(neg_j, "text, watermarks")

if __name__ == "__main__":
    unittest.main()
