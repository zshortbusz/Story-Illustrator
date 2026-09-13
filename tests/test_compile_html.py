import unittest
from pipeline.compile_html import split_quotes, render_dialogue_content, compile_manifest_to_html

class TestCompileHTML(unittest.TestCase):
    def test_split_quotes_dialogue(self):
        text = 'He said, "Run now!" and turned.'
        segments = split_quotes(text)
        # Should have unbolded, then bolded quotes, then unbolded
        bold_texts = [s["text"] for s in segments if s["bold"]]
        self.assertIn('"Run now!"', "".join(bold_texts))

    def test_render_dialogue_content(self):
        content = 'Kaelen whispered, "Follow me." Then paused.'
        rendered = render_dialogue_content(content)
        self.assertIn('<strong class="q">"Follow me."</strong>', rendered)

    def test_compile_manifest_to_html(self):
        manifest = {
            "story_title": "Test Odyssey",
            "active_profile": "sdxl_base",
            "blocks": [
                {
                    "chunk_id": "chunk_000",
                    "text": 'The adventure began. "Wait," she called.',
                    "illustration": None
                }
            ]
        }
        html_out = compile_manifest_to_html(manifest, project_dir=".")
        self.assertIn("Test Odyssey", html_out)
        self.assertIn('<strong class="q">"Wait,"</strong>', html_out)
        self.assertIn("story-paragraph", html_out)
        self.assertIn("Automated Story Illustrator", html_out)

if __name__ == "__main__":
    unittest.main()
