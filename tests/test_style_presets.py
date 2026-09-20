"""
tests/test_style_presets.py: Unit tests for style preset inference and response parsing.
"""

import unittest
from unittest.mock import MagicMock
from pipeline.llm_client import (
    LMStudioClient,
    infer_styles,
    parse_styles_response,
    _slugify_style_local
)


class TestStylePresets(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock(spec=LMStudioClient)

    def test_slugify_style_local(self):
        self.assertEqual(_slugify_style_local("Charcoal & Carbon Noir"), "charcoal_carbon_noir")
        self.assertEqual(_slugify_style_local("1970s 35mm Kodachrome!"), "1970s_35mm_kodachrome")
        self.assertEqual(_slugify_style_local("   "), "style")

    def test_parse_styles_response_json_array(self):
        raw = """```json
[
  {
    "id": "charcoal_test",
    "name": "Charcoal Noir",
    "description": "expressive carbon dust on paper with chiaroscuro lighting"
  },
  {
    "id": "oil_test",
    "name": "Impasto Oil",
    "description": "thick textured paint applied with palette knife"
  }
]
```"""
        styles = parse_styles_response(raw, category="art", requested_count=2)
        self.assertEqual(len(styles), 2)
        self.assertEqual(styles[0]["id"], "charcoal_test")
        self.assertEqual(styles[0]["name"], "Charcoal Noir")
        self.assertEqual(styles[0]["category"], "art")
        self.assertEqual(styles[1]["name"], "Impasto Oil")

    def test_parse_styles_response_markdown_bullets(self):
        raw = """Here are the styles:
1. **1970s Kodachrome**: Vintage 35mm warm color film with saturated tones and lens flare.
2. **1890s Wet Plate**: Antique tintype with silver emulsion swirls and chemical vignetting.
3. **1950s Tri-X Noir**: High-contrast black and white documentary film grain.
"""
        styles = parse_styles_response(raw, category="photography", requested_count=3)
        self.assertEqual(len(styles), 3)
        self.assertEqual(styles[0]["name"], "1970s Kodachrome")
        self.assertEqual(styles[0]["category"], "photography")
        self.assertIn("35mm", styles[0]["description"])
        self.assertEqual(styles[1]["name"], "1890s Wet Plate")
        self.assertEqual(styles[2]["name"], "1950s Tri-X Noir")

    def test_parse_styles_response_fallbacks(self):
        # Empty or gibberish output should safely fall back to curated presets
        styles = parse_styles_response("", category="art", requested_count=6)
        self.assertEqual(len(styles), 6)
        for s in styles:
            self.assertEqual(s["category"], "art")
            self.assertTrue(s["name"])
            self.assertTrue(s["description"])

        photo_styles = parse_styles_response("invalid response", category="photography", requested_count=3)
        self.assertEqual(len(photo_styles), 3)
        for s in photo_styles:
            self.assertEqual(s["category"], "photography")

    def test_infer_styles_art(self):
        self.mock_client.chat_text.return_value = """[
  {"name": "Gothic Charcoal", "description": "Smudged carbon dust on rough cold-press paper with deep blacks"},
  {"name": "Ethereal Watercolor", "description": "Luminous wet-on-wet pigments with translucent blooms"}
]"""
        results = infer_styles(
            llm_client=self.mock_client,
            model="test-model",
            theme_text="Gothic dark mystery",
            category="art",
            count=2
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "Gothic Charcoal")
        self.assertEqual(results[0]["category"], "art")

        # Verify system prompt targeted art tools and avoided clichés
        call_args = self.mock_client.chat_text.call_args[1]
        messages = call_args["messages"]
        system_content = messages[0]["content"]
        self.assertIn("art director", system_content.lower())
        self.assertIn("charcoal", system_content.lower())

    def test_infer_styles_photography_with_existing(self):
        self.mock_client.chat_text.return_value = """[
  {"name": "1940s Noir Silver Gelatin", "description": "Monochrome silver-halide film with dramatic venetian blind shadows"}
]"""
        results = infer_styles(
            llm_client=self.mock_client,
            model="test-model",
            theme_text="Period noir detective",
            category="photography",
            count=1,
            existing_styles=["1970s Kodachrome", "1890s Wet Plate"]
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "1940s Noir Silver Gelatin")

        # Verify existing styles were included in avoid clause
        call_args = self.mock_client.chat_text.call_args[1]
        messages = call_args["messages"]
        user_content = messages[1]["content"]
        self.assertIn("1970s Kodachrome", user_content)
        self.assertIn("1890s Wet Plate", user_content)


if __name__ == "__main__":
    unittest.main()
